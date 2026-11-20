"""Giữ nguyên phần ngoài phạm vi Audit; không suy đoán ngữ nghĩa bằng từ khóa."""
from __future__ import annotations

import json

from .planner_audit import PlannerAuditResult


def _signature(value, ignored):
    payload = {key: item for key, item in value.items() if key not in ignored}
    if 'fact_ids' in payload:
        payload['fact_ids'] = sorted(payload['fact_ids'])
    if 'required_evidence' in payload:
        payload['required_evidence'] = sorted(
            _signature(req, {'requirement_id'}) for req in payload['required_evidence'])
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def validate_revision_scope(initial: dict, candidate: dict, audit: PlannerAuditResult) -> list[str]:
    """ID mới không dùng để đoán Issue cũ; phần được bảo vệ phải khớp nội dung."""
    old = initial['issues']
    new = candidate['issues']
    issue_ids = {item['issue_id'] for item in old}
    full = set(audit.misdirected_issue_ids) & issue_ids
    requirements = set(audit.unsearchable_requirement_ids)
    for directive in audit.repair_directives:
        if directive.issue_id not in issue_ids:
            continue
        if directive.requirement_ids:
            requirements.update(directive.requirement_ids)
        else:
            full.add(directive.issue_id)
    # Issue phụ thuộc một Issue bị thay cấu trúc cũng có thể cần sửa theo.
    while True:
        dependents = {item['issue_id'] for item in old if set(item['depends_on']) & full}
        expanded = full | dependents
        if expanded == full:
            break
        full = expanded
    allow_structure = bool(full or audit.uncovered_requests)
    if not full and not requirements and not audit.uncovered_requests:
        return ['REVISION_SCOPE_UNSPECIFIED: Audit chưa chỉ rõ phần cần sửa.']
    errors = []
    if not allow_structure and len(new) != len(old):
        errors.append('REVISION_SCOPE: Không được đổi số Issue khi chỉ sửa Requirement.')
    mapping = {}
    matched = set()
    protected = []
    for issue in old:
        if issue['issue_id'] in full:
            continue
        partial = any(r['requirement_id'] in requirements for r in issue['required_evidence'])
        ignored = {'issue_id', 'depends_on'} | ({'required_evidence'} if partial else set())
        matches = [item for item in new if _signature(item, ignored) == _signature(issue, ignored)]
        if len(matches) != 1 or matches[0]['issue_id'] in matched:
            errors.append(f"REVISION_SCOPE: {issue['issue_id']} bị sửa ngoài phạm vi hoặc không thể đối chiếu duy nhất.")
            continue
        counterpart = matches[0]
        mapping[issue['issue_id']] = counterpart['issue_id']
        matched.add(counterpart['issue_id'])
        protected.append((issue, counterpart))
        if partial:
            if not allow_structure and len(issue['required_evidence']) != len(counterpart['required_evidence']):
                errors.append(f"REVISION_SCOPE: {issue['issue_id']} thay số Requirement ngoài phạm vi.")
            remaining = [_signature(r, {'requirement_id'}) for r in counterpart['required_evidence']]
            for req in issue['required_evidence']:
                if req['requirement_id'] in requirements:
                    continue
                signature = _signature(req, {'requirement_id'})
                if signature not in remaining:
                    errors.append(f"REVISION_SCOPE: {req['requirement_id']} đang được bảo vệ nhưng đã thay đổi.")
                else:
                    remaining.remove(signature)
    for issue, counterpart in protected:
        expected = {mapping.get(dep) for dep in issue['depends_on']}
        if None in expected or expected != set(counterpart['depends_on']):
            errors.append(f"REVISION_SCOPE: {issue['issue_id']} thay dependency ngoài phạm vi.")
    return errors
