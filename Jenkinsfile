pipeline {
    agent any

    triggers {
        cron('H */6 * * *')
    }

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
        timeout(time: 6, unit: 'HOURS')
    }

    parameters {
        booleanParam(
            name: 'AUTO_DISCOVER',
            defaultValue: true,
            description: 'Discover and build every missing Chromium release tag'
        )
        booleanParam(
            name: 'BACKFILL_GITHUB',
            defaultValue: false,
            description: 'Upload existing R2 binaries missing from GitHub Releases without rebuilding them'
        )
        string(
            name: 'CHROMIUM_VERSION',
            defaultValue: '',
            description: 'Optional exact Chromium version. When set, only this version is built.'
        )
        string(
            name: 'MIN_MAJOR',
            defaultValue: '150',
            description: 'Oldest Chromium major to consider in automatic mode'
        )
    }

    environment {
        BUILD_IMAGE = 'modlabs/chromium-ffmpeg-builder:local'
        AWS_IMAGE = 'amazon/aws-cli:latest'

        CHROMIUM_SRC = 'https://chromium.googlesource.com/chromium/src.git'
        CHROMIUM_DEPS_RAW = 'https://raw.githubusercontent.com/chromium/chromium'
        FFMPEG_GIT = 'https://chromium.googlesource.com/chromium/third_party/ffmpeg.git'

        R2_ENDPOINT = 'https://089237543c212eb2e79cae28a2ec3810.r2.cloudflarestorage.com'
        R2_BUCKET = 'chromium-ffmpeg'
        R2_PREFIX = 'chromium'
        R2_PUBLIC_BASE = 'https://chromium-ffmpeg.modlabs.cc'

        GITHUB_REPOSITORY = 'ModLabsCC/chromium-ffmpeg-prebuilt'
    }

    stages {
        stage('Validate') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail

                    MIN_MAJOR="${MIN_MAJOR:-150}"
                    CHROMIUM_VERSION="${CHROMIUM_VERSION:-}"
                    AUTO_DISCOVER="${AUTO_DISCOVER:-true}"
                    BACKFILL_GITHUB="${BACKFILL_GITHUB:-false}"

                    case "$MIN_MAJOR" in
                        ''|*[!0-9]*)
                            echo 'MIN_MAJOR must be numeric' >&2
                            exit 1
                            ;;
                    esac

                    if [[ -n "$CHROMIUM_VERSION" ]]; then
                        case "$CHROMIUM_VERSION" in
                            *[!0-9.]*|.*|*.|*..*)
                                echo "Invalid Chromium version: $CHROMIUM_VERSION" >&2
                                exit 1
                                ;;
                        esac

                        IFS=. read -r a b c d extra <<< "$CHROMIUM_VERSION"
                        if [[ -n "${extra:-}" || -z "$a" || -z "$b" || -z "$c" || -z "$d" ]]; then
                            echo "Invalid Chromium version: $CHROMIUM_VERSION" >&2
                            exit 1
                        fi
                    elif [[ "$AUTO_DISCOVER" != true && "$BACKFILL_GITHUB" != true ]]; then
                        echo 'Enable AUTO_DISCOVER or BACKFILL_GITHUB, or set CHROMIUM_VERSION' >&2
                        exit 1
                    fi
                '''
            }
        }

        stage('Prepare build image') {
            steps {
                sh 'docker build --pull --tag "$BUILD_IMAGE" .'
            }
        }

        stage('Discover releases') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'r2-credentials',
                        usernameVariable: 'AWS_ACCESS_KEY_ID',
                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                    )
                ]) {
                    sh '''#!/usr/bin/env bash
                        set -euo pipefail
                        rm -rf work out
                        mkdir -p work out

                        MIN_MAJOR="${MIN_MAJOR:-150}"
                        CHROMIUM_VERSION="${CHROMIUM_VERSION:-}"
                        AUTO_DISCOVER="${AUTO_DISCOVER:-true}"

                        if [[ -n "$CHROMIUM_VERSION" ]]; then
                            printf '%s\n' "$CHROMIUM_VERSION" > work/candidates.txt
                        elif [[ "$AUTO_DISCOVER" == true ]]; then
                            docker run --rm \
                                --volumes-from "$(hostname)" \
                                --workdir "${WORKSPACE}" \
                                --user "$(id -u):$(id -g)" \
                                --env HOME=/tmp \
                                --env MIN_MAJOR="$MIN_MAJOR" \
                                --env CHROMIUM_SRC \
                                "${BUILD_IMAGE}" \
                                bash -ceu '
                                    git ls-remote --tags --refs "$CHROMIUM_SRC" \
                                        | awk "{print \\$2}" \
                                        | sed "s#refs/tags/##" \
                                        | grep -E "^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$" \
                                        | awk -F. -v min="$MIN_MAJOR" "\\$1 >= min" \
                                        | sort -Vu
                                ' > work/candidates.txt
                        else
                            : > work/candidates.txt
                        fi

                        docker run --rm \
                            --env AWS_ACCESS_KEY_ID \
                            --env AWS_SECRET_ACCESS_KEY \
                            --env AWS_DEFAULT_REGION=auto \
                            "${AWS_IMAGE}" \
                            s3api list-objects-v2 \
                                --endpoint-url "$R2_ENDPOINT" \
                                --bucket "$R2_BUCKET" \
                                --prefix "$R2_PREFIX/" \
                                --query 'Contents[].Key' \
                                --output text \
                            | tr '\t' '\n' \
                            | awk -F/ -v prefix="$R2_PREFIX" '$1 == prefix && $2 ~ /^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$/ && $3 == "linux-x64" && $4 == "manifest.json" { print $2 }' \
                            > work/published.txt

                        awk 'FILENAME == ARGV[1] { published[$0] = 1; next } !($0 in published)' \
                            work/published.txt work/candidates.txt \
                            > work/versions.txt

                        echo "Chromium candidates: $(wc -l < work/candidates.txt)"
                        echo "Already published: $(wc -l < work/published.txt)"
                        echo "Chromium versions queued: $(wc -l < work/versions.txt)"
                    '''
                }
            }
        }

        stage('Resolve FFmpeg revisions') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail

                    if [[ ! -s work/versions.txt ]]; then
                        : > work/mappings.tsv
                        : > work/revisions.txt
                        echo 'Nothing to resolve.'
                        exit 0
                    fi

                    docker run --rm \
                        --volumes-from "$(hostname)" \
                        --workdir "${WORKSPACE}" \
                        --user "$(id -u):$(id -g)" \
                        --env HOME=/tmp \
                        --env CHROMIUM_DEPS_RAW \
                        "${BUILD_IMAGE}" \
                        bash -ceu '
                            python3 - <<"PY"
import concurrent.futures
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

base = os.environ["CHROMIUM_DEPS_RAW"]
versions = [v.strip() for v in Path("work/versions.txt").read_text().splitlines() if v.strip()]
workers = min(12, max(1, len(versions)))
sha_re = re.compile(r"[0-9a-f]{40}")

def resolve(version):
    url = f"{base}/{version}/DEPS"
    last_error = None

    for attempt in range(6):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "ModLabsCC-chromium-ffmpeg-prebuilt/1"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                text = response.read().decode("utf-8")

            pos = text.find("ffmpeg_revision")
            if pos < 0:
                raise RuntimeError("ffmpeg_revision not found")

            hashes = sha_re.findall(text[pos:pos + 500])
            if not hashes:
                raise RuntimeError("FFmpeg revision SHA not found")

            return version, hashes[0]
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 or 500 <= exc.code < 600:
                retry_after = exc.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = min(20.0, 1.0 * (2 ** attempt)) + random.uniform(0.0, 0.75)
                print(
                    f"{version}: HTTP {exc.code}, retrying in {delay:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(delay)
                continue
            raise
        except Exception as exc:
            last_error = exc
            if attempt < 5:
                delay = min(10.0, 0.5 * (2 ** attempt)) + random.uniform(0.0, 0.5)
                time.sleep(delay)
                continue
            break

    raise RuntimeError(f"{version}: {last_error}")

results = {}
errors = []
with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
    futures = {pool.submit(resolve, version): version for version in versions}
    completed = 0
    for future in concurrent.futures.as_completed(futures):
        version = futures[future]
        try:
            resolved_version, revision = future.result()
            results[resolved_version] = revision
        except Exception as exc:
            errors.append(str(exc))
        completed += 1
        if completed % 25 == 0 or completed == len(versions):
            print(f"Resolved {completed}/{len(versions)} Chromium versions", file=sys.stderr, flush=True)

if errors:
    print("Resolver failures:", file=sys.stderr)
    for error in errors:
        print(f"  {error}", file=sys.stderr)
    raise SystemExit(1)

with Path("work/mappings.tsv").open("w") as out:
    for version in versions:
        print(version, results[version], sep=chr(9), file=out)
PY
                        '

                    cut -f2 work/mappings.tsv | sort -u > work/revisions.txt
                    echo "Chromium versions: $(wc -l < work/mappings.tsv)"
                    echo "Unique FFmpeg revisions: $(wc -l < work/revisions.txt)"
                '''
            }
        }

        stage('Build and publish') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'r2-credentials',
                        usernameVariable: 'AWS_ACCESS_KEY_ID',
                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                    ),
                    string(credentialsId: 'chromium-ffmpeg-github-token', variable: 'GH_TOKEN')
                ]) {
                    sh '''#!/usr/bin/env bash
                        set -euo pipefail

                        download_r2() {
                            local version="$1" object="$2" destination="$3"
                            local source="s3://$R2_BUCKET/$R2_PREFIX/$version/linux-x64/$object"

                            echo "Downloading $source"
                            docker run --rm \
                                --volumes-from "$(hostname)" \
                                --workdir "${WORKSPACE}" \
                                --user "$(id -u):$(id -g)" \
                                --env HOME=/tmp \
                                --env AWS_ACCESS_KEY_ID \
                                --env AWS_SECRET_ACCESS_KEY \
                                --env AWS_DEFAULT_REGION=auto \
                                --env AWS_RETRY_MODE=standard \
                                --env AWS_MAX_ATTEMPTS=6 \
                                "${AWS_IMAGE}" \
                                s3 cp "$source" "$destination" \
                                    --endpoint-url "$R2_ENDPOINT" \
                                    --only-show-errors
                        }

                        publish_github_release() {
                            local version="$1" revision="$2" sha256="$3" lib="$4" out_dir="$5"
                            local tag="chromium-$version"
                            local release_json="$out_dir/github-release.json"
                            local status release_body release_id asset_id

                            status="$(curl --silent --show-error --retry 6 --retry-all-errors --retry-delay 2 \
                                --output "$release_json" --write-out '%{http_code}' \
                                --header 'Accept: application/vnd.github+json' \
                                --header "Authorization: Bearer $GH_TOKEN" \
                                --header 'X-GitHub-Api-Version: 2022-11-28' \
                                "https://api.github.com/repos/$GITHUB_REPOSITORY/releases/tags/$tag")"

                            if [[ "$status" == 200 ]]; then
                                read -r release_id asset_id < <(
                                    docker run --rm \
                                        --volumes-from "$(hostname)" \
                                        --workdir "${WORKSPACE}" \
                                        "${BUILD_IMAGE}" \
                                        python3 -c 'import json, sys; release = json.load(open(sys.argv[1])); print(release["id"], next((asset["id"] for asset in release["assets"] if asset["name"] == "libffmpeg.so"), ""))' \
                                        "$release_json"
                                )

                                if [[ -n "$asset_id" ]]; then
                                    echo "GitHub release $tag already contains libffmpeg.so"
                                    rm -f "$release_json"
                                    return
                                fi
                            elif [[ "$status" != 404 ]]; then
                                cat "$release_json" >&2
                                return 1
                            fi

                            if [[ -z "$revision" || -z "$sha256" ]]; then
                                download_r2 "$version" manifest.json "$out_dir/manifest.json"

                                read -r revision sha256 < <(
                                    docker run --rm \
                                        --volumes-from "$(hostname)" \
                                        --workdir "${WORKSPACE}" \
                                        "${BUILD_IMAGE}" \
                                        python3 -c 'import json, re, sys; manifest = json.load(open(sys.argv[1])); version = sys.argv[2]; revision = manifest["ffmpeg_commit"]; sha256 = manifest["sha256"]; assert manifest["chromium"] == version and re.fullmatch(r"[0-9a-f]{40}", revision) and re.fullmatch(r"[0-9a-f]{64}", sha256); print(revision, sha256)' \
                                        "$out_dir/manifest.json" "$version"
                                )
                                printf '%s  libffmpeg.so\n' "$sha256" > "$out_dir/libffmpeg.so.sha256"
                            fi

                            if [[ "$status" == 404 ]]; then
                                release_body="$(printf \
                                    '{"tag_name":"%s","target_commitish":"%s","name":"Chromium %s","body":"Linux x64 libffmpeg.so built from FFmpeg commit %s. SHA-256: %s","make_latest":"false"}' \
                                    "$tag" "$GIT_COMMIT" "$version" "$revision" "$sha256")"
                                curl --fail-with-body --silent --show-error \
                                    --request POST \
                                    --header 'Accept: application/vnd.github+json' \
                                    --header "Authorization: Bearer $GH_TOKEN" \
                                    --header 'X-GitHub-Api-Version: 2022-11-28' \
                                    --data "$release_body" \
                                    --output "$release_json" \
                                    "https://api.github.com/repos/$GITHUB_REPOSITORY/releases"
                                release_id="$(docker run --rm \
                                    --volumes-from "$(hostname)" \
                                    --workdir "${WORKSPACE}" \
                                    "${BUILD_IMAGE}" \
                                    python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["id"])' \
                                    "$release_json")"
                            fi

                            if [[ ! -f "$lib" ]]; then
                                download_r2 "$version" libffmpeg.so "$lib"
                                printf '%s  %s\n' "$sha256" "$lib" | sha256sum --check
                            fi

                            curl --fail-with-body --silent --show-error \
                                --request POST \
                                --header 'Accept: application/vnd.github+json' \
                                --header "Authorization: Bearer $GH_TOKEN" \
                                --header 'X-GitHub-Api-Version: 2022-11-28' \
                                --header 'Content-Type: application/octet-stream' \
                                --data-binary "@$lib" \
                                --output /dev/null \
                                "https://uploads.github.com/repos/$GITHUB_REPOSITORY/releases/$release_id/assets?name=libffmpeg.so"
                            echo "Published GitHub release $tag"

                            rm -f "$release_json"
                        }

                        if [[ "${BACKFILL_GITHUB:-false}" == true ]]; then
                            if [[ -n "${CHROMIUM_VERSION:-}" ]]; then
                                grep -Fx "$CHROMIUM_VERSION" work/published.txt > work/backfill.txt || true
                            else
                                cp work/published.txt work/backfill.txt
                            fi

                            echo "R2 binaries queued for GitHub backfill: $(wc -l < work/backfill.txt)"
                            while IFS= read -r version; do
                                [[ -n "$version" ]] || continue

                                OUT_DIR="out/$version/linux-x64"
                                LIB="$OUT_DIR/libffmpeg.so"
                                mkdir -p "$OUT_DIR"
                                publish_github_release "$version" '' '' "$LIB" "$OUT_DIR"
                                rm -f "$LIB"
                            done < work/backfill.txt
                        fi

                        if [[ ! -s work/revisions.txt ]]; then
                            echo 'Nothing new to build; R2 already contains all discovered releases.'
                            exit 0
                        fi

                        while IFS= read -r revision; do
                            [[ -n "$revision" ]] || continue

                            versions_file="work/versions-$revision.txt"
                            awk -F '\t' -v revision="$revision" '$2 == revision { print $1 }' work/mappings.tsv > "$versions_file"

                            version_count="$(wc -l < "$versions_file")"
                            echo "Building FFmpeg $revision once for $version_count Chromium version(s)"

                            BUILD_DIR="work/build-$revision"
                            rm -rf "$BUILD_DIR"

                            docker run --rm \
                                --volumes-from "$(hostname)" \
                                --workdir "${WORKSPACE}" \
                                --user "$(id -u):$(id -g)" \
                                --env HOME=/tmp \
                                --env FFMPEG_REV="$revision" \
                                --env FFMPEG_GIT \
                                "${BUILD_IMAGE}" \
                                bash -ceu '
                                    ROOT_DIR="$PWD"
                                    BUILD_DIR="work/build-$FFMPEG_REV"
                                    rm -rf "$BUILD_DIR"
                                    mkdir -p "$BUILD_DIR"
                                    cd "$BUILD_DIR"

                                    git clone -q "$FFMPEG_GIT" ffmpeg
                                    cd ffmpeg
                                    git checkout -q "$FFMPEG_REV"

                                    chmod +x "$ROOT_DIR/build.sh"
                                    "$ROOT_DIR/build.sh" linux-x64

                                    cd "$ROOT_DIR"
                                    install -Dm755 "$BUILD_DIR/ffmpeg/libffmpeg.so" "$BUILD_DIR/libffmpeg.so"
                                    file "$BUILD_DIR/libffmpeg.so"
                                    readelf -h "$BUILD_DIR/libffmpeg.so" | grep -q "DYN (Shared object file)"
                                    sha256sum "$BUILD_DIR/libffmpeg.so" > "$BUILD_DIR/libffmpeg.so.sha256"
                                '

                            LIB="$BUILD_DIR/libffmpeg.so"
                            SHA256="$(cut -d ' ' -f1 "$BUILD_DIR/libffmpeg.so.sha256")"

                            while IFS= read -r version; do
                                [[ -n "$version" ]] || continue

                                OUT_DIR="out/$version/linux-x64"
                                mkdir -p "$OUT_DIR"
                                printf '%s  libffmpeg.so\n' "$SHA256" > "$OUT_DIR/libffmpeg.so.sha256"

                                cat > "$OUT_DIR/manifest.json" <<EOF
{
  "chromium": "$version",
  "ffmpeg_commit": "$revision",
  "platform": "linux",
  "arch": "x64",
  "sha256": "$SHA256",
  "download_url": "$R2_PUBLIC_BASE/$R2_PREFIX/$version/linux-x64/libffmpeg.so"
}
EOF

                                DEST="s3://$R2_BUCKET/$R2_PREFIX/$version/linux-x64"
                                publish_github_release "$version" "$revision" "$SHA256" "$LIB" "$OUT_DIR"

                                docker run --rm \
                                    --volumes-from "$(hostname)" \
                                    --workdir "${WORKSPACE}" \
                                    --env AWS_ACCESS_KEY_ID \
                                    --env AWS_SECRET_ACCESS_KEY \
                                    --env AWS_DEFAULT_REGION=auto \
                                    "${AWS_IMAGE}" \
                                    s3 cp "$LIB" "$DEST/libffmpeg.so" \
                                        --endpoint-url "$R2_ENDPOINT" \
                                        --content-type application/octet-stream

                                docker run --rm \
                                    --volumes-from "$(hostname)" \
                                    --workdir "${WORKSPACE}" \
                                    --env AWS_ACCESS_KEY_ID \
                                    --env AWS_SECRET_ACCESS_KEY \
                                    --env AWS_DEFAULT_REGION=auto \
                                    "${AWS_IMAGE}" \
                                    s3 cp "$OUT_DIR/libffmpeg.so.sha256" "$DEST/libffmpeg.so.sha256" \
                                        --endpoint-url "$R2_ENDPOINT" \
                                        --content-type text/plain

                                docker run --rm \
                                    --volumes-from "$(hostname)" \
                                    --workdir "${WORKSPACE}" \
                                    --env AWS_ACCESS_KEY_ID \
                                    --env AWS_SECRET_ACCESS_KEY \
                                    --env AWS_DEFAULT_REGION=auto \
                                    "${AWS_IMAGE}" \
                                    s3 cp "$OUT_DIR/manifest.json" "$DEST/manifest.json" \
                                        --endpoint-url "$R2_ENDPOINT" \
                                        --content-type application/json \
                                        --cache-control 'public,max-age=300'

                                echo "Published Chromium $version from FFmpeg $revision"
                            done < "$versions_file"

                            rm -rf "$BUILD_DIR" "$versions_file"
                        done < work/revisions.txt
                    '''
                }
            }
        }

        stage('Archive manifests') {
            steps {
                archiveArtifacts(
                    artifacts: 'out/**/manifest.json,out/**/libffmpeg.so.sha256',
                    allowEmptyArchive: true,
                    fingerprint: true
                )
            }
        }
    }

    post {
        always {
            cleanWs(deleteDirs: true, disableDeferredWipeout: true, notFailBuild: true)
        }
    }
}
