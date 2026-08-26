from pathlib import Path


def test_backfill_checks_github_before_fetching_r2_manifest():
    jenkinsfile = Path(__file__).with_name("Jenkinsfile").read_text()
    backfill = jenkinsfile.split('if [[ "${BACKFILL_GITHUB:-false}" == true ]]', 1)[1]
    backfill = backfill.split('if [[ ! -s work/revisions.txt ]]', 1)[0]

    publish = backfill.index("publish_github_release")
    manifest = backfill.find("manifest.json")
    assert manifest < 0 or publish < manifest
