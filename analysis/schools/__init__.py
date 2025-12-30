from analysis.schools.smc.report import generate_smc_report

SCHOOL_REGISTRY = {
    "smc": generate_smc_report,
    # "ict": generate_ict_report,
    # "wyckoff": generate_wyckoff_report,
    # "harmonic": generate_harmonic_report,
}

def run_school(school: str, symbol: str, snapshot: dict) -> str:
    school = (school or "").lower().strip()
    fn = SCHOOL_REGISTRY.get(school)
    if not fn:
        return f"⚠️ المدرسة '{school}' غير مدعومة حاليًا."
    return fn(symbol, snapshot)
