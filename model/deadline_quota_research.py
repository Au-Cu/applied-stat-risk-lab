"""Research-only, current-year quota features from the immutable R2 evidence.

This adapter intentionally does not import the production quota_features module:
that frozen module uses a registration-start cutoff and historical fallback.
Here the cutoff is the formal registration deadline, and a missing current-year
net quota stays missing. Source transcription eligibility, label-unit linkage,
and production promotion are three separate decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re

import numpy as np
import pandas as pd
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize

BEIJING = timezone(timedelta(hours=8))
POLICIES = ("strict_ordinary", "special_scope_sensitivity")

# Explicit aliases, not substring/fuzzy matches. Multiple-college school labels
# cannot be assigned one college's quota, even if that quota is perfectly read.
UNIT_ALIASES = {
    "中央财经大学": {"统计与数学学院": "统计与数学学院"},
    "上海交通大学": {"数学科学学院": "数学科学学院"},
    "南京大学": {"数学系": "数学学院", "数学学院": "数学学院"},
    "西南财经大学": {"统计学院": "统计与数据科学学院", "统计与数据科学学院": "统计与数据科学学院"},
}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_time(value):
    """Never infer an unavailable clock time on the deadline date."""
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return result.replace(tzinfo=BEIJING) if result.tzinfo is None else result.astimezone(BEIJING)


def time_is_visible(value, deadline, precision="date"):
    instant = parse_time(value)
    if instant is None:
        return False
    if precision == "date" or len(str(value)) == 10:
        return instant.date() < deadline.date()
    return instant <= deadline


def visibility(record):
    deadline = parse_time(record.get("registration_deadline"))
    if deadline is None:
        return False, "missing_registration_deadline"
    published = record.get("effective_publish_date")
    precision = record.get("publication_precision", "date")
    # A known later replacement may not inherit the parent page's old date.
    instant = parse_time(published)
    if instant is not None and (
        instant.date() > deadline.date()
        or (precision != "date" and len(str(published)) > 10 and instant > deadline)
    ):
        return False, "published_or_revised_after_deadline"
    # Every necessary component needs its own date, or a before-deadline capture
    # explicitly covering all components. The R2 flag certifies all source IDs.
    captured = parse_time(record.get("capture_time"))
    if record.get("observed_before_deadline") is True and captured is not None and captured <= deadline:
        return True, "captured_before_deadline"
    if not time_is_visible(published, deadline, precision):
        return False, "publication_date_or_version_unknown_or_deadline_day_ambiguous"
    fields = []
    if number(record.get("reported_exam_quota")) is not None:
        fields.append("exam_quota_publish_date")
    else:
        fields.extend(("total_plan_publish_date", "accepted_recommended_publish_date"))
    if any(not time_is_visible(record.get(field), deadline, precision) for field in fields):
        return False, "component_publication_not_verified_before_deadline"
    return True, "dated_official_reconstruction_not_contemporaneous_archive"


def assess_record(record, policy):
    if policy not in POLICIES:
        raise ValueError(policy)
    reasons = []
    status = str(record.get("review_status") or "")
    if status.startswith("规则"):
        reasons.append("rule_candidate_not_reviewed")
    if not status or "待核" in status or "不入模" in status:
        reasons.append("record_review_unresolved")
    if record.get("source_grade") != "A-official":
        reasons.append("not_official_source")
    if record.get("study_mode") != "全日制":
        reasons.append("fulltime_scope_not_verified")
    if str(record.get("major_code")) != "025200":
        reasons.append("wrong_major")
    if not record.get("source_ids") or not record.get("source_sha256"):
        reasons.append("missing_source_identity_or_hash")
    visible, basis = visibility(record)
    if not visible:
        reasons.append(basis)
    kind = record.get("record_kind")
    direct = number(record.get("reported_exam_quota"))
    total = number(record.get("total_plan_same_scope"))
    actual_recommended = number(record.get("accepted_recommended"))
    net = None
    method = "unavailable"
    if kind == "推免后统考公告" and direct is not None:
        net, method = direct, "official_post_actual_recommendation_net"
    elif kind == "总计划及实际接收推免" and total is not None and actual_recommended is not None:
        net, method = total - actual_recommended, "same_scope_total_minus_actual_accepted_recommended"
        if direct is not None and not math.isclose(direct, net):
            reasons.append("direct_and_subtracted_net_conflict")
    else:
        reasons.append("not_verified_post_actual_recommendation_net")
    if net is not None and (net < 0 or not net.is_integer()):
        reasons.append("invalid_net_count")
    if net == 0:
        reasons.append("zero_regular_seats_no_ordinary_cohort_forecast")
    ordinary = record.get("ordinary_scope_verified") is True or bool(
        re.search(r"明确不含专项|不含专项计划|已剔除专项|明确不含少干", str(record.get("special_scope") or ""))
    )
    if policy == "strict_ordinary" and not ordinary:
        reasons.append("special_plan_exclusion_not_verified")
    return {
        "record_id": record["record_id"], "school": record["school"], "year": int(record["year"]),
        "unit": record.get("unit"), "policy": policy, "evidence_eligible": not reasons,
        "reason_codes": ";".join(reasons), "current_net_quota": net,
        "net_method": method, "ordinary_scope_verified": ordinary,
        "record_kind": kind, "study_mode": record.get("study_mode"),
        "reported_exam_quota": direct, "total_plan_same_scope": total,
        "accepted_recommended": actual_recommended,
        "planned_recommended": number(record.get("planned_recommended")),
        "special_scope": record.get("special_scope"),
        "availability_basis": basis, "effective_publish_date": record.get("effective_publish_date"),
        "exam_quota_publish_date": record.get("exam_quota_publish_date"),
        "total_plan_publish_date": record.get("total_plan_publish_date"),
        "accepted_recommended_publish_date": record.get("accepted_recommended_publish_date"),
        "registration_deadline": record.get("registration_deadline"),
        "source_ids": ";".join(record.get("source_ids") or []),
        "source_sha256": ";".join(record.get("source_sha256") or []),
        "primary_source_url": record.get("primary_source_url"),
        "supporting_urls": ";".join(record.get("supporting_urls") or []),
        "source_locator": record.get("source_locator"),
        "parent_model_eligible": record.get("model_eligible", False),
        "review_status": status,
        "historical_snapshot_limitation": record.get("historical_snapshot_limitation"),
    }


def build_ledger(payload, schools):
    school_units = schools.set_index("school").unit_2026.to_dict()
    calendars = {int(c["year"]): parse_time(c["registration_deadline"]) for c in payload.get("calendars", [])}
    rows = []
    for policy in POLICIES:
        for source in payload["records"]:
            if calendars and parse_time(source.get("registration_deadline")) != calendars.get(int(source["year"])):
                raise ValueError(f"Registration calendar conflict: {source['record_id']}")
            r = assess_record(source, policy)
            aliases = UNIT_ALIASES.get(r["school"], {})
            canonical = aliases.get(r["unit"])
            model_unit = school_units.get(r["school"], "")
            r["canonical_unit"] = canonical
            r["target_unit_2026"] = model_unit
            r["unit_link_verified"] = canonical is not None and model_unit in aliases and aliases[model_unit] == canonical
            r["linked_for_research"] = r["evidence_eligible"] and r["unit_link_verified"]
            if not r["unit_link_verified"]:
                r["reason_codes"] += (";" if r["reason_codes"] else "") + "school_label_unit_link_not_verified"
            rows.append(r)
    ledger = pd.DataFrame(rows)
    # Never silently pick/sum two colleges or conflicting versions.
    for _, group in ledger[ledger.linked_for_research].groupby(["policy", "school", "year"]):
        if len(group) != 1:
            ledger.loc[group.index, "linked_for_research"] = False
            ledger.loc[group.index, "reason_codes"] += ";duplicate_school_year_requires_resolution"
    return ledger


def attach_current_features(frame, ledger, policy):
    """Use exact school/year keys only; no carry-forward and no zero quotas."""
    selected = ledger[(ledger.policy == policy) & ledger.linked_for_research]
    lookup = {(r.school, int(r.year)): r for r in selected.itertuples()}
    rows = []
    for item in frame[["school", "year"]].itertuples(index=False):
        key = (item.school, int(item.year))
        current = lookup.get(key)
        previous = lookup.get((item.school, int(item.year) - 1))
        count = float(current.current_net_quota) if current is not None else np.nan
        change = np.nan
        if current is not None and previous is not None and current.canonical_unit == previous.canonical_unit:
            change = math.log2(count / float(previous.current_net_quota))
        rows.append({"quota_current_net": count, "quota_log2": math.log2(count) if np.isfinite(count) else np.nan,
            "quota_log2_change": change, "quota_available": int(current is not None),
            "quota_change_available": int(np.isfinite(change)),
            "quota_record_id": current.record_id if current is not None else None,
            "quota_unit": current.canonical_unit if current is not None else None,
            "quota_source_year": int(item.year) if current is not None else np.nan,
            "quota_ordinary_scope_verified": bool(current.ordinary_scope_verified) if current is not None else None,
            "quota_effective_publish_date": current.effective_publish_date if current is not None else None,
            "quota_registration_deadline": current.registration_deadline if current is not None else None,
            "quota_availability_basis": current.availability_basis if current is not None else None})
    result = frame.copy()
    values = pd.DataFrame(rows, index=result.index)
    for column in values:
        result[column] = values[column]
    return result


@dataclass
class QuotaDesign:
    kind: str
    level_center: float
    slope_sd: float = 10.

    @classmethod
    def fit(cls, train, kind, slope_sd=10.):
        observed = train.loc[train.quota_available.eq(1), "quota_log2"].dropna()
        return cls(kind, float(observed.mean()) if len(observed) else 0., slope_sd)

    def transform(self, frame):
        names = ["quota_available", "quota_change_available"]
        arrays = [frame.quota_available.to_numpy(float), frame.quota_change_available.to_numpy(float)]
        prior_sds = [5., 5.]
        # Zero means 'no covariate adjustment' in the design only, never N=0.
        if "level" in self.kind:
            arrays.append((frame.quota_log2 - self.level_center).fillna(0.).to_numpy(float))
            names.append("quota_log2_centered"); prior_sds.append(self.slope_sd)
        if "change" in self.kind:
            arrays.append(frame.quota_log2_change.fillna(0.).to_numpy(float))
            names.append("quota_log2_change"); prior_sds.append(self.slope_sd)
        return np.column_stack(arrays), np.square(prior_sds), names


@dataclass
class CovariateState:
    observations: pd.DataFrame
    design: QuotaDesign
    school_variance: float
    innovation_variance: float
    intercept: float
    intercept_variance: float
    factor: tuple
    residual_precision: np.ndarray
    ones_precision: np.ndarray
    x: np.ndarray
    prior_variances: np.ndarray
    converged: bool
    slope_summary: list

    def predict(self, row):
        test = pd.DataFrame([row])
        xstar = self.design.transform(test)[0][0]
        match = self.observations.school.to_numpy() == row["school"]
        cross = self.school_variance * match + self.x @ (self.prior_variances * xstar)
        priorvar = self.school_variance + self.innovation_variance + np.sum(self.prior_variances * xstar**2)
        a = cho_solve(self.factor, cross, check_finite=False)
        center = self.intercept + cross @ self.residual_precision
        variance = priorvar - cross @ a + (1. - cross @ self.ones_precision)**2 * self.intercept_variance
        return float(center), float(max(variance, .01))


def fit_covariate_state(observations, design, initial_variances=(200., 100.)):
    """Gaussian random-intercept model with regularized global quota slopes.

    beta ~ N(0,D) is integrated once as X D X'. REML estimates the same two
    school/state variances as V6. Beta and intercept uncertainty enter prediction;
    variance hyperparameters remain empirical-Bayes plug-in estimates as in V6.
    """
    frame = observations.copy().reset_index(drop=True)
    x, prior, names = design.transform(frame)
    schools = frame.school.to_numpy()
    school_kernel = (schools[:, None] == schools[None, :]).astype(float)
    feature_covariance = (x * prior) @ x.T
    y = frame.margin.to_numpy(float)
    one = np.ones(len(y))
    noise = frame.observation_variance.to_numpy(float)

    def objective(logvars, details=False):
        a, u = np.exp(logvars)
        covariance = a * school_kernel + np.diag(u + noise) + feature_covariance
        factor = cho_factor(covariance, lower=True, check_finite=False)
        vi_one = cho_solve(factor, one, check_finite=False)
        vi_y = cho_solve(factor, y, check_finite=False)
        info = one @ vi_one
        mu = one @ vi_y / info
        residual = y - mu
        vi_resid = cho_solve(factor, residual, check_finite=False)
        loss = .5 * (2 * np.log(np.diag(factor[0])).sum() + np.log(info) + residual @ vi_resid)
        return (mu, 1. / info, factor, vi_resid, vi_one) if details else float(loss)

    optimum = minimize(objective, np.log(initial_variances), method="L-BFGS-B", bounds=[(-8., 11.)] * 2)
    mu, muvar, factor, residual, vi_one = objective(optimum.x, details=True)
    beta = prior * (x.T @ residual)
    vi_x = cho_solve(factor, x, check_finite=False)
    correction = prior * (x.T @ vi_one)
    beta_cov = np.diag(prior) - (prior[:, None] * (x.T @ vi_x)) * prior[None, :] + np.outer(correction, correction) * muvar
    summary = [{"feature": name, "posterior_mean": float(b), "posterior_sd": float(np.sqrt(max(beta_cov[j, j], 0.))),
        "prior_sd": float(np.sqrt(prior[j]))} for j, (name, b) in enumerate(zip(names, beta))]
    return CovariateState(frame, design, *map(float, np.exp(optimum.x)), float(mu), float(muvar),
        factor, residual, vi_one, x, prior, bool(optimum.success), summary)
