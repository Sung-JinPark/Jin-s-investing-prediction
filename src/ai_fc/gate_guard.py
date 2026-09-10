"""T06 — **금지 행위 감지기.**

계약 `questions/portfolio_prereg_v1.yaml` 의 `stopping_rules.never` 세 항목은 문장으로만
있으면 지켜지지 않는다. 셋 다 **조용히** 일어날 수 있기 때문이다.

| 금지 행위 | 조용한 이유 |
|---|---|
| `gate_arithmetic_change` | SQL 한 글자만 바꿔도 판정이 뒤집히는데 diff 는 한 줄이다 |
| `post_hoc_failed_tagging` | 성적 나쁜 행에 failed 를 붙이면 대표 Brier 가 내려간다 |
| (원장 행 삭제) | append-only 규약 위반. 지운 행은 흔적이 남지 않는다 |

이 모듈은 **git 을 기준선으로** 쓴다. 저장소 안에 별도 스냅샷 파일을 두면 그 파일 자체가
같이 조작될 수 있고, 낡으면 거짓 안심을 준다. 커밋 이력은 그보다 지우기 어렵다.

## 판정이 아니라 감지다

여기서 참을 내면 "위반이 있었을 수 있다"이지 "위반했다"가 아니다. 예컨대 원장 행 삭제로
보이는 것이 실제로는 파일 재정렬일 수 있다. 그래도 **막는다** — 재정렬할 이유가 없기 때문이고,
정당한 사유가 있다면 사람이 사유와 함께 통과시켜야지 감지기가 알아서 봐주면 안 된다.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

#: 게이트 산술의 정본 문자열 — 한 글자라도 바뀌면 위반이다.
GATE_SQL_LITERALS = (
    "COUNT(DISTINCT r.question_id) >= 50 AND AVG(r.brier) < 0.18",
    "COUNT(DISTINCT r.question_id) >= 30 AND AVG(r.brier) < 0.20",
)
GATE_CONFIG_LITERALS = (
    'GATE_P3 = {"n": 50, "brier": 0.18}',
)
SCHEMA_RELATIVE = Path("src/ai_fc/db/schema.sql")
CONFIG_RELATIVE = Path("src/ai_fc/config.py")
LEDGER_RELATIVE = Path("calibration/ledger.csv")
OVERRIDES_RELATIVE = Path("calibration/research_status_overrides.csv")

#: 기준선 ref. CI 는 병합 기준을, 로컬은 직전 커밋을 쓴다.
DEFAULT_BASELINE = "HEAD"


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"[{self.rule}] {self.detail}"


def _git(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "")


def check_gate_arithmetic(root: Path) -> list[Violation]:
    """DISTINCT 50 ∧ AVG(brier) < 0.18 이 문자 그대로 남아 있는가."""
    out: list[Violation] = []
    schema_path = root / SCHEMA_RELATIVE
    if not schema_path.is_file():
        return [Violation("gate_arithmetic_change", f"{SCHEMA_RELATIVE} 가 없다")]
    schema = schema_path.read_text(encoding="utf-8")
    for literal in GATE_SQL_LITERALS:
        if literal not in schema:
            out.append(Violation("gate_arithmetic_change",
                                 f"{SCHEMA_RELATIVE} 에서 게이트 산술이 사라졌다: {literal!r}"))
    config_path = root / CONFIG_RELATIVE
    if config_path.is_file():
        config_src = config_path.read_text(encoding="utf-8")
        for literal in GATE_CONFIG_LITERALS:
            if literal not in config_src:
                out.append(Violation("gate_arithmetic_change",
                                     f"{CONFIG_RELATIVE} 에서 문턱 상수가 바뀌었다: {literal!r}"))
    return out


def _removed_lines(root: Path, relative: Path, baseline: str) -> list[str] | None:
    """`baseline` 대비 삭제된 줄. git 을 쓸 수 없으면 None(판정 보류)."""
    code, diff = _git(root, "diff", "--unified=0", baseline, "--", str(relative))
    if code != 0:
        return None
    removed = []
    for line in diff.splitlines():
        if line.startswith("---"):
            continue
        if line.startswith("-") and line[1:].strip():
            removed.append(line[1:])
    return removed


def check_ledger_append_only(root: Path, baseline: str = DEFAULT_BASELINE) -> list[Violation]:
    """원장에서 줄이 사라졌는가. 헤더 변경도 삭제로 잡는다."""
    removed = _removed_lines(root, LEDGER_RELATIVE, baseline)
    if removed is None:
        return [Violation("ledger_append_only",
                          f"git 기준선({baseline})을 읽을 수 없어 판정을 보류한다 — "
                          "보류는 통과가 아니다")]
    if removed:
        head = " / ".join(r[:60] for r in removed[:3])
        return [Violation("ledger_append_only",
                          f"원장에서 {len(removed)}줄이 사라졌다 (append-only 위반): {head}")]
    return []


def check_failed_tags_not_changed_post_hoc(root: Path,
                                           baseline: str = DEFAULT_BASELINE) -> list[Violation]:
    """이미 기록된 failed/degraded 태그가 사후에 바뀌었는가.

    새 행 **추가**는 허용한다(새 예측이 생기면 태그도 생긴다). 금지되는 것은
    **기존 행의 변경·삭제**다 — 성적을 본 뒤 표본을 빼는 것과 구별되지 않는다.
    """
    out: list[Violation] = []
    removed = _removed_lines(root, OVERRIDES_RELATIVE, baseline)
    if removed is None:
        out.append(Violation("post_hoc_failed_tagging",
                             f"git 기준선({baseline})을 읽을 수 없어 판정을 보류한다"))
    elif removed:
        out.append(Violation("post_hoc_failed_tagging",
                             f"오버라이드 메타에서 {len(removed)}줄이 사라지거나 바뀌었다: "
                             + " / ".join(r[:60] for r in removed[:3])))

    # 예측 파일의 frontmatter 태그가 바뀌는 것도 같은 조작이다 — forecasts/ 는 전체가 불변이다.
    code, diff = _git(root, "diff", "--name-only", baseline, "--", "forecasts")
    if code == 0 and diff.strip():
        out.append(Violation("post_hoc_failed_tagging",
                             "forecasts/ 가 수정됐다 (불변 규약 위반): "
                             + ", ".join(diff.split()[:5])))
    return out


def check_all(root: Path, baseline: str = DEFAULT_BASELINE) -> list[Violation]:
    return (check_gate_arithmetic(root)
            + check_ledger_append_only(root, baseline)
            + check_failed_tags_not_changed_post_hoc(root, baseline))


def guard_lines(violations: list[Violation]) -> list[str]:
    if not violations:
        return ["금지 행위 감지 0건 — 게이트 산술·원장 append-only·failed 태그 전부 무변경"]
    return [f"금지 행위 감지 {len(violations)}건 — 즉시 중단 사유"] + [f"  {v}" for v in violations]
