import ipaddress
import json
import re
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

MAX_DESCRIPTION_CHARS = 24000
SCREENSHOT_DIR = Path("./data/screenshots")
MAX_REQUIREMENTS = 40
NAVIGATION_TIMEOUT_MS = 25000


class UnsafeURL(ValueError):
    pass


def _assert_public_http_url(url: str) -> None:
    """Basic SSRF defense; every browser request and redirect is checked."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeURL("Only HTTP and HTTPS URLs are allowed.")
    host = parts.hostname
    if not host:
        raise UnsafeURL("URL must contain a hostname.")
    if host.lower() in {"localhost", "localhost.localdomain"} or host.endswith(".localhost") or host.endswith(".local"):
        raise UnsafeURL("Local and private-network hosts are not allowed.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, None)]
        except socket.gaierror as exc:
            raise UnsafeURL("Hostname could not be resolved.") from exc
    if not addresses or any(
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified
        for addr in addresses
    ):
        raise UnsafeURL("URLs resolving to private or non-public IP addresses are not allowed.")


def detect_ats(url: str, html: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    haystack = f"{host} {html[:250000].lower()}"
    patterns = [
        ("greenhouse", ("greenhouse.io",)),
        ("lever", ("jobs.lever.co", "lever.co")),
        ("ashby", ("ashbyhq.com",)),
        ("workday", ("myworkdayjobs.com", "workday.com")),
        ("smartrecruiters", ("smartrecruiters.com",)),
        ("workable", ("apply.workable.com", "workable.com")),
        ("icims", ("icims.com",)),
        ("jobvite", ("jobvite.com",)),
        ("linkedin", ("linkedin.com",)),
    ]
    for name, markers in patterns:
        if any(marker in haystack for marker in markers):
            return name
    return "generic"


def _clean(value) -> str:
    if not value:
        return ""
    return " ".join(str(value).split()).strip()


def normalize_salary(raw: str, description: str = "") -> dict:
    """Parse common JobPosting baseSalary JSON-LD without discarding the source value."""
    result = {"salary_min": None, "salary_max": None, "salary_currency": "", "salary_period": ""}
    if raw:
        try:
            value = json.loads(raw)
            # Accept MonetaryAmount -> QuantitativeValue, or a direct QuantitativeValue.
            if isinstance(value, dict):
                result["salary_currency"] = str(value.get("currency") or "").upper()
                amount = value.get("value", value)
                if isinstance(amount, dict):
                    result["salary_min"] = _number(amount.get("minValue", amount.get("value")))
                    result["salary_max"] = _number(amount.get("maxValue", amount.get("value")))
                    unit = amount.get("unitText") or value.get("unitText") or ""
                    result["salary_period"] = _period(unit)
                if not result["salary_currency"]:
                    result["salary_currency"] = str(value.get("currencyCode") or "").upper()
        except (ValueError, TypeError):
            pass
    # Fallback for visible text such as ₹70L–₹90L/year. Values are converted to INR.
    if result["salary_min"] is None and result["salary_max"] is None:
        match = re.search(r"(?:₹|INR\s*)\s*([\d,.]+)\s*(L| lakh| lakhs| crore| cr)?\s*(?:-|–|to)\s*(?:₹|INR\s*)?\s*([\d,.]+)\s*(L| lakh| lakhs| crore| cr)?", description, re.I)
        if match:
            def amount(num, unit):
                n = float(num.replace(',', ''))
                u = (unit or '').strip().lower()
                if u in {'l', 'lakh', 'lakhs'}: n *= 100000
                elif u in {'crore', 'cr'}: n *= 10000000
                return int(n)
            result["salary_min"] = amount(match.group(1), match.group(2))
            result["salary_max"] = amount(match.group(3), match.group(4) or match.group(2))
            result["salary_currency"] = "INR"
            result["salary_period"] = "YEAR" if re.search(r"/\s*(year|yr|annum)|per\s+year", description, re.I) else ""
    return result

def _number(value):
    try:
        return int(float(value)) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None

def _period(value: str) -> str:
    value = str(value).strip().upper()
    if value in {"YEAR", "YEARLY", "ANNUAL", "ANNUALLY"}: return "YEAR"
    if value in {"MONTH", "MONTHLY"}: return "MONTH"
    if value in {"HOUR", "HOURLY"}: return "HOUR"
    if value in {"WEEK", "WEEKLY"}: return "WEEK"
    return value[:20]


async def inspect_job_page(url: str) -> dict:
    _assert_public_http_url(url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1000},
            java_script_enabled=True,
            accept_downloads=False,
        )
        page = await context.new_page()
        warnings = []

        async def guard_route(route):
            try:
                _assert_public_http_url(route.request.url)
            except (UnsafeURL, ValueError):
                await route.abort()
                return
            if route.request.resource_type in {"media", "font"}:
                await route.abort()
                return
            await route.continue_()

        await page.route("**/*", guard_route)
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            if response and response.status >= 400:
                warnings.append(f"Page returned HTTP {response.status}.")
            try:
                await page.wait_for_load_state("networkidle", timeout=4000)
            except PlaywrightTimeoutError:
                warnings.append("Page did not reach network idle; inspected currently rendered content.")
            await page.wait_for_timeout(350)
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            job_screenshot = SCREENSHOT_DIR / f"job_{int(time.time() * 1000)}_description.png"
            await page.screenshot(path=str(job_screenshot), full_page=True, animations="disabled")

            payload = await page.evaluate("""() => {
              const text = (el) => (el?.innerText || el?.textContent || '').replace(/\\s+/g, ' ').trim();
              const first = (selectors) => {
                for (const s of selectors) {
                  const el = document.querySelector(s);
                  const t = text(el);
                  if (t && t.length > 2) return t;
                }
                return '';
              };
              const meta = (names) => {
                for (const n of names) {
                  const el = document.querySelector(`meta[property="${n}"], meta[name="${n}"]`);
                  if (el?.content) return el.content.trim();
                }
                return '';
              };
              const jsonLd = [];
              for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
                try {
                  const value = JSON.parse(script.textContent || 'null');
                  if (Array.isArray(value)) jsonLd.push(...value); else if (value) jsonLd.push(value);
                } catch {}
              }
              const flatten = (v) => {
                if (!v || typeof v !== 'object') return [];
                if (Array.isArray(v)) return v.flatMap(flatten);
                return [v, ...Object.values(v).flatMap(flatten)];
              };
              const jobs = flatten(jsonLd).filter(x => {
                const t = x['@type'];
                return t === 'JobPosting' || (Array.isArray(t) && t.includes('JobPosting'));
              });
              const job = jobs[0] || {};
              const org = job.hiringOrganization || {};
              const jobLocation = job.jobLocation;
              const locText = (v) => {
                if (!v) return '';
                const vals = Array.isArray(v) ? v : [v];
                return vals.map(x => {
                  const a = x.address || x;
                  return [a.addressLocality, a.addressRegion, a.addressCountry].filter(Boolean).join(', ');
                }).filter(Boolean).join(' / ');
              };
              const descriptionEl = document.querySelector(
                '[data-automation="jobDescription"], #jobDescriptionText, .job-description, .jobDescription, [class*="job-description"], [class*="jobDescription"], [data-testid*="description"], article'
              );
              const bodyText = text(descriptionEl) || text(document.body);
              const labels = [...document.querySelectorAll('input,textarea,select,[role="combobox"]')]
                .map(el => {
                  const id = el.id;
                  const label = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
                  return {
                    tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '',
                    name: el.getAttribute('name') || '',
                    id: id || '',
                    label: text(label) || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '',
                    required: !!el.required || el.getAttribute('aria-required') === 'true'
                  };
                }).slice(0, 100);
              return {
                page_title: document.title || '',
                canonical_url: document.querySelector('link[rel="canonical"]')?.href || location.href,
                h1: first(['h1', '[data-automation="jobTitle"]', '[data-testid="job-title"]']),
                og_title: meta(['og:title']),
                description_meta: meta(['description', 'og:description']),
                job_title: job.title || '',
                company_name: org.name || '',
                location: locText(jobLocation) || first(['[data-automation="jobLocation"]', '[class*="location"]', '[data-testid*="location"]']),
                employment_type: Array.isArray(job.employmentType) ? job.employmentType.join(', ') : (job.employmentType || ''),
                work_mode: job.jobLocationType || '',
                salary_text: job.baseSalary ? JSON.stringify(job.baseSalary) : '',
                description: bodyText.slice(0, 24000),
                form_fields: labels,
                jsonld_requirements: job.qualifications || job.experienceRequirements || '',
                body_preview: text(document.body).slice(0, 3000),
                has_captcha: !!document.querySelector('iframe[src*="captcha"], [class*="captcha"], [id*="captcha"]'),
                has_application_form: !!document.querySelector('form input, form textarea, form select, [role="form"] input')
              };
            }""")

            html = await page.content()
            ats = detect_ats(page.url, html)
            job_title = _clean(payload.get("job_title") or payload.get("h1") or payload.get("og_title"))
            company = _clean(payload.get("company_name"))
            description = _clean(payload.get("description") or payload.get("description_meta"))
            requirements = payload.get("jsonld_requirements") or ""
            if isinstance(requirements, (dict, list)):
                requirements = json.dumps(requirements, ensure_ascii=False)
            if not requirements:
                requirements = await page.evaluate("""() => {
                  const out = [];
                  for (const h of document.querySelectorAll('h2,h3,h4')) {
                    const title = (h.innerText || '').toLowerCase();
                    if (!/(requirement|qualification|what you bring|must have|preferred|what we're looking for|skills)/.test(title)) continue;
                    let node = h.nextElementSibling;
                    for (let i=0; node && i<4; i++, node=node.nextElementSibling) {
                      if (node.matches('ul,ol')) for (const li of node.querySelectorAll('li')) out.push((li.innerText || '').trim());
                      else if (node.matches('p')) out.push((node.innerText || '').trim());
                    }
                  }
                  return [...new Set(out.filter(Boolean))].slice(0,40);
                }""")
            if isinstance(requirements, str):
                try:
                    decoded = json.loads(requirements)
                    requirements_list = decoded if isinstance(decoded, list) else [requirements]
                except Exception:
                    requirements_list = [requirements] if requirements else []
            else:
                requirements_list = requirements if isinstance(requirements, list) else [str(requirements)]
            requirements_list = [_clean(x) for x in requirements_list if _clean(x)][:MAX_REQUIREMENTS]

            # Inspect the first application step only. Never click submit/finalize controls.
            application_url = ""
            application_screenshot = ""
            application_fields = []
            try:
                apply_locator = page.locator("a, button, [role='button']").filter(has_text=re.compile(r"^\s*apply(?:\s+for\s+this\s+job)?\s*$", re.I)).first
                if await apply_locator.count() and await apply_locator.is_visible():
                    before_url = page.url
                    try:
                        async with page.expect_navigation(wait_until="domcontentloaded", timeout=5000):
                            await apply_locator.click(timeout=3000)
                    except PlaywrightTimeoutError:
                        # Many ATS pages open the form inline or in a new tab instead of navigating.
                        await page.wait_for_timeout(800)
                    if page.url != before_url:
                        _assert_public_http_url(page.url)
                    application_url = page.url
                    application_fields = await page.evaluate("""() => [...document.querySelectorAll('input,textarea,select,[role=combobox]')].slice(0,100).map(el => {
                      const id = el.id; const label = id ? document.querySelector(`label[for=\"${CSS.escape(id)}\"]`) : null;
                      return {tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '', name: el.getAttribute('name') || '', id: id || '', label: (label?.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim(), required: !!el.required || el.getAttribute('aria-required') === 'true'};
                    })""")
                    application_screenshot_path = SCREENSHOT_DIR / f"job_{int(time.time() * 1000)}_application.png"
                    await page.screenshot(path=str(application_screenshot_path), full_page=True, animations="disabled")
                    application_screenshot = str(application_screenshot_path.as_posix())
                else:
                    warnings.append("No clearly labelled Apply control was found; application flow was not opened.")
            except Exception as exc:
                warnings.append(f"Application flow could not be fully inspected ({type(exc).__name__}); job-page inspection was retained.")

            if payload.get("has_captcha"):
                warnings.append("A CAPTCHA-like element was detected. Manual intervention may be required; it will not be bypassed.")
            if not payload.get("has_application_form"):
                warnings.append("No obvious application form was detected on the initial page.")
            if not job_title:
                warnings.append("Could not confidently extract a job title.")
            if not description:
                warnings.append("Could not extract a job description.")
            salary = normalize_salary(_clean(payload.get("salary_text")), description)
            return {
                "inspection_status": "completed",
                "page_title": _clean(payload.get("page_title"))[:500],
                "final_url": page.url,
                "ats_platform": ats,
                "job_title": job_title[:500],
                "company_name": company[:300],
                "location": _clean(payload.get("location"))[:300],
                "employment_type": _clean(payload.get("employment_type"))[:120],
                "work_mode": _clean(payload.get("work_mode"))[:120],
                "salary_text": _clean(payload.get("salary_text")),
                **salary,
                "job_screenshot_path": job_screenshot.as_posix(),
                "application_screenshot_path": application_screenshot,
                "application_url": application_url,
                "application_fields": application_fields,
                "description": description[:MAX_DESCRIPTION_CHARS],
                "requirements": requirements_list,
                "detected_fields": payload.get("form_fields", []),
                "warnings": warnings,
                "error_message": "",
            }
        except UnsafeURL:
            raise
        except PlaywrightTimeoutError:
            raise RuntimeError("Timed out while loading the job page.")
        except Exception as exc:
            raise RuntimeError(f"Could not inspect job page ({type(exc).__name__}).")
        finally:
            await context.close()
            await browser.close()
