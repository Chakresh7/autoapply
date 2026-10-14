from app.services.job_page_inspector import normalize_salary

def test_normalizes_cartesia_salary_jsonld():
    raw = '{"@type":"MonetaryAmount","currency":"INR","value":{"@type":"QuantitativeValue","minValue":7000000,"maxValue":9000000,"unitText":"YEAR"}}'
    assert normalize_salary(raw) == {"salary_min": 7000000, "salary_max": 9000000, "salary_currency": "INR", "salary_period": "YEAR"}

def test_missing_salary_is_empty():
    assert normalize_salary("") == {"salary_min": None, "salary_max": None, "salary_currency": "", "salary_period": ""}
