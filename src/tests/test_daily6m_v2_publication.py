"""daily6m v2 publisher: real Git races on disposable bare remotes; no market/model writes."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("v2publisher", ROOT / "tools/publish_daily6m_v2_shadow.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def write(root, relative, value):
    p = root / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(value.encode("utf-8"))


def commit(root, message):
    git(root, "add", ".")
    git(root, "-c", "user.name=fixture", "-c", "user.email=fixture@example.test", "commit", "-m", message)


@pytest.fixture
def repos(tmp_path):
    remote, root, rival = [tmp_path / n for n in ("remote.git", "publisher", "rival")]
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)], capture_output=True, check=True)
    subprocess.run(["git", "clone", "--config", "core.autocrlf=false", str(remote), str(root)], capture_output=True, check=True)
    write(root, M.STORE + "ledgers/forecasts.jsonl", 'base\n')
    write(root, M.STORE + "derived/scorecard.json", '{"n_runs": 0}\n')
    write(root, M.STORE + "runs/base.json", '{}\n')
    commit(root, "base")
    git(root, "push", "origin", "HEAD:main")
    subprocess.run(["git", "clone", "--config", "core.autocrlf=false", str(remote), str(rival)], capture_output=True, check=True)
    return root, rival, tmp_path


def own_edit(root, value="new"):
    path = root / (M.STORE + "ledgers/forecasts.jsonl")
    path.write_bytes(path.read_bytes() + (value + "\n").encode())
    write(root, M.STORE + "derived/scorecard.json", json.dumps({"n_runs": value}) + "\n")
    write(root, M.STORE + f"runs/{value}.json", json.dumps({"id": value}) + "\n")


def test_real_rejected_push_replays_on_latest_main_and_keeps_both_ledger_appends(repos):
    root, rival, tmp = repos
    own_edit(root)
    bases = []
    def race(n, attempt):
        if n == 1:
            own_edit(rival, "concurrent")
            commit(rival, "concurrent writer")
            git(rival, "push", "origin", "HEAD:main")
    def replay(attempt, report):
        bases.append((attempt / (M.STORE + "ledgers/forecasts.jsonl")).read_text())
        own_edit(attempt)
        return True
    r = M.publish(root, report=tmp / "report.json", parent=tmp, replay_fn=replay, before_push=race, sleep=lambda _: None)
    assert r["committed"] and [a["status"] for a in r["attempts"]] == ["race", "published"]
    assert bases == ['base\nconcurrent\n']
    assert git(root, "show", "origin/main:" + M.STORE + "ledgers/forecasts.jsonl") == 'base\nconcurrent\nnew'
    assert git(root, "show", "origin/main:" + M.STORE + "runs/base.json") == '{}'
    assert json.loads((tmp / "report.json").read_text())["status"] == "published"


def test_competing_publisher_already_published_same_origin_no_duplicate(repos):
    root, rival, tmp = repos
    own_edit(root)
    def race(n, _):
        own_edit(rival)
        write(rival, "other.txt", "a concurrent update\n")
        commit(rival, "same origin")
        git(rival, "push", "origin", "HEAD:main")
    r = M.publish(root, report=tmp / "report.json", parent=tmp, replay_fn=lambda *_: True, before_push=race, sleep=lambda _: None)
    assert not r["committed"] and r["status"] == "unchanged"
    assert len(r["attempts"]) == 2


def test_three_races_fail_loudly_and_preserve_report(repos):
    root, rival, tmp = repos
    own_edit(root)
    def race(n, _):
        write(rival, "other.txt", str(n))
        commit(rival, "writer " + str(n))
        git(rival, "push", "origin", "HEAD:main")
    def replay(attempt, _):
        own_edit(attempt)
        return True
    with pytest.raises(M.PublicationError, match="three fresh-main"):
        M.publish(root, report=tmp / "report.json", parent=tmp, replay_fn=replay, before_push=race, sleep=lambda _: None)
    report = json.loads((tmp / "report.json").read_text())
    assert len(report["attempts"]) == 3 and not report["committed"]


@pytest.mark.parametrize("kind", ["ledger_rewrite", "run_rewrite", "delete", "source_edit", "prereg", "v1_store", "outside"])
def test_history_and_scope_violations_never_publish(repos, kind):
    root, _, tmp = repos
    if kind == "ledger_rewrite":
        write(root, M.STORE + "ledgers/forecasts.jsonl", 'replaced\n')
    elif kind == "run_rewrite":
        write(root, M.STORE + "runs/base.json", '{"changed": true}\n')
    elif kind == "delete":
        (root / (M.STORE + "runs/base.json")).unlink()
    elif kind == "source_edit":
        write(root, M.STORE + "ledgers/approvals.jsonl", '{}\n')
    elif kind == "prereg":
        write(root, M.STORE + "prereg/design_constants_v1.json", '{}\n')
    elif kind == "v1_store":
        write(root, "data/timeseries_daily6m/ledgers/forecasts.jsonl", '{}\n')
        git(root, "add", "data/timeseries_daily6m/ledgers/forecasts.jsonl")
    else:
        write(root, "official.json", '{}\n')
        git(root, "add", "official.json")
    before = git(root, "rev-parse", "origin/main")
    with pytest.raises(M.PublicationError):
        M.publish(root, report=tmp / "report.json", parent=tmp, sleep=lambda _: None)
    assert git(root, "rev-parse", "origin/main") == before
    assert not json.loads((tmp / "report.json").read_text())["committed"]


def test_readiness_failure_on_retry_never_reuses_previous_staged_result(repos):
    root, rival, tmp = repos
    own_edit(root)
    def race(n, _):
        write(rival, "other.txt", "source changed")
        commit(rival, "source update")
        git(rival, "push", "origin", "HEAD:main")
    def replay(*_):
        raise subprocess.CalledProcessError(1, ["readiness"])
    with pytest.raises(subprocess.CalledProcessError):
        M.publish(root, report=tmp / "report.json", parent=tmp, before_push=race, replay_fn=replay, sleep=lambda _: None)
    assert git(root, "show", "origin/main:" + M.STORE + "ledgers/forecasts.jsonl") == 'base'


def test_scorecard_overwrite_and_verdict_append_are_allowed(repos):
    root, _, tmp = repos
    write(root, M.STORE + "derived/scorecard.json", '{"n_runs": 9}\n')
    write(root, M.STORE + "ledgers/verdicts.jsonl", '{"kind": "h1_p_values_frozen"}\n')
    assert M.commit_changes(root) is True
    assert "scorecard.json" in git(root, "show", "--name-only", "HEAD")


def test_nothing_staged_when_paths_do_not_exist(repos):
    root, _, _ = repos
    assert M.commit_changes(root) is False


def test_workflow_uses_v2_publisher_without_rebase_or_pages():
    d = yaml.safe_load((ROOT / ".github/workflows/daily6m-v2-shadow.yml").read_text(encoding="utf-8"))
    steps = d["jobs"]["shadow"]["steps"]
    publish = next(s for s in steps if s.get("id") == "commit")
    assert "publish_daily6m_v2_shadow.py" in publish["run"] and "git pull --rebase" not in publish["run"]
    assert not any("pages.yml" in str(s.get("run", "")) for s in steps)
