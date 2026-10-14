import ipaddress
import json
import socket
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

MAX_DESCRIPTION_CHARS = 24000
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
            if payload.get("has_captcha"):
                warnings.append("A CAPTCHA-like element was detected. Manual intervention may be required; it will not be bypassed.")
            if not payload.get("has_application_form"):
                warnings.append("No obvious application form was detected on the initial page.")
            if not job_title:
                warnings.append("Could not confidently extract a job title.")
            if not description:
                warnings.append("Could not extract a job description.")
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
                "salary_text": _clean(payload.get("salary_text"))[:300],
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
