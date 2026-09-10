"""P3 게이트 중간검토 · 부정 결과 선언 · 금지 행위 감지 (T06).

    PYTHONUTF8=1 python tools/gate_review.py              # 상태 인쇄 (읽기 전용)
    PYTHONUTF8=1 python tools/gate_review.py --markdown   # 리포트 본문 인쇄
    PYTHONUTF8=1 python tools/gate_review.py --guard-only --baseline origin/main
                                                          # CI 용 — 위반 시 exit 1

규율 (tools/c5_status.py 와 동일 형):
- 읽기 전용. 어떤 파일도 쓰지 않는다. 리포트는 stdout 으로만 낸다 —
  손으로 갱신하는 상태 파일을 만들면 낡은 상태가 잘못된 다음 행동을 부른다.
- 페일클로즈: 판정 보류는 통과가 아니다. git 기준선을 못 읽으면 위반으로 센다.
- '통과' 라는 단어를 쓰지 않는다 (계약 status_wording.forbidden_words).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc import gate_guard, gate_review  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="P3 게이트 중간검토 · 금지 행위 감지")
    ap.add_argument("--markdown", action="store_true", help="리포트 본문을 마크다운으로 인쇄")
    ap.add_argument("--guard-only", action="store_true", help="금지 행위 감지만 실행 (CI 용)")
    ap.add_argument("--baseline", default=gate_guard.DEFAULT_BASELINE,
                    help="원장·태그 비교 기준 git ref (기본 HEAD)")
    args = ap.parse_args()

    violations = gate_guard.check_all(ROOT, args.baseline)
    if args.guard_only:
        for line in gate_guard.guard_lines(violations):
            print(line)
        return 1 if violations else 0

    review = gate_review.interim_review(ROOT)
    if args.markdown:
        print(gate_review.render_markdown(review, today=date.today().isoformat()))
        return 1 if violations else 0

    v = gate_review.verdict(ROOT)
    print(f"게이트 상태 표현 : {review['state']}")
    print(f"해소 문항        : {v.n_questions}/{review['threshold_questions']}")
    print(f"행 평균 (정본)   : {review['brier_primary_rows']}")
    print(f"문항 등가중      : {review['brier_per_question']}")
    ci = review.get("ci90") or []
    print(f"클러스터 CI90    : "
          + (f"[{ci[0]:.5f}, {ci[1]:.5f}]" if len(ci) == 2 else "—"))
    print(f"중간검토 문턱    : {', '.join(str(m) for m in review['milestones'])} "
          f"(도달 {', '.join(str(m) for m in v.milestones_reached) or '없음'})")
    print(f"부정 선언 조건   : 문항 {review['negative_at']}+ ∧ CI90 하한 > "
          f"{review['negative_ci_lower_above']}")
    print(f"판정             : {v.reason}")
    print()
    for line in gate_guard.guard_lines(violations):
        print(line)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
