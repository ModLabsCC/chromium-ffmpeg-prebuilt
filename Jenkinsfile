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
        BUILD_IMAGE = 'ubuntu:24.04'
        CHROMIUM_SRC = 'https://chromium.googlesource.com/chromium/src.git'
        CHROMIUM_GITILES = 'https://chromium.googlesource.com/chromium/src'
        FFMPEG_GIT = 'https://chromium.googlesource.com/chromium/third_party/ffmpeg.git'
        NWJS_BUILD_SH = 'https://raw.githubusercontent.com/nwjs-ffmpeg-prebuilt/nwjs-ffmpeg-prebuilt/master/build.sh'

        R2_ENDPOINT = 'https://089237543c212eb2e79cae28a2ec3810.r2.cloudflarestorage.com'
        R2_BUCKET = 'chromium-ffmpeg'
        R2_PREFIX = 'chromium'
        R2_PUBLIC_BASE = 'https://chromium-ffmpeg.modlabs.cc'
    }

    stages {
        stage('Validate') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail

                    MIN_MAJOR="${MIN_MAJOR:-150}"
                    CHROMIUM_VERSION="${CHROMIUM_VERSION:-}"
                    AUTO_DISCOVER="${AUTO_DISCOVER:-true}"

                    case "$MIN_MAJOR" in
                        ''|*[!0-9]*)
                            echo 'MIN_MAJOR must be numeric' >&2
                            exit 1
                            ;;
                    esac

                    if [[ -n "$CHROMIUM_VERSION" ]]; then
                        case "$CHROMIUM_VERSION" in
                            *[!0-9.]*|.*|*.|*..* )
                                echo "Invalid Chromium version: $CHROMIUM_VERSION" >&2
                                exit 1
                                ;;
                        esac

                        IFS=. read -r a b c d extra <<< "$CHROMIUM_VERSION"
                        if [[ -n "${extra:-}" || -z "$a" || -z "$b" || -z "$c" || -z "$d" ]]; then
                            echo "Invalid Chromium version: $CHROMIUM_VERSION" >&2
                            exit 1
                        fi
                    elif [[ "$AUTO_DISCOVER" != true ]]; then
                        echo 'Either AUTO_DISCOVER must be enabled or CHROMIUM_VERSION must be set' >&2
                        exit 1
                    fi
                '''
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

                        if [[ -n "$CHROMIUM_VERSION" ]]; then
                            printf '%s\n' "$CHROMIUM_VERSION" > work/candidates.txt
                        else
                            docker run --rm \
                                --volumes-from "$(hostname)" \
                                --workdir "${WORKSPACE}" \
                                --env MIN_MAJOR="$MIN_MAJOR" \
                                --env CHROMIUM_SRC \
                                "${BUILD_IMAGE}" \
                                bash -ceu '
                                    apt-get update >/dev/null
                                    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                        ca-certificates git >/dev/null

                                    git ls-remote --tags --refs "$CHROMIUM_SRC" \
                                        | awk "{print \\$2}" \
                                        | sed "s#refs/tags/##" \
                                        | grep -E "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$" \
                                        | awk -F. -v min="$MIN_MAJOR" "\\$1 >= min" \
                                        | sort -Vu
                                ' > work/candidates.txt
                        fi

                        docker run --rm -i \
                            --volumes-from "$(hostname)" \
                            --workdir "${WORKSPACE}" \
                            --env AWS_ACCESS_KEY_ID \
                            --env AWS_SECRET_ACCESS_KEY \
                            --env AWS_DEFAULT_REGION=auto \
                            --env R2_ENDPOINT \
                            --env R2_BUCKET \
                            --env R2_PREFIX \
                            "${BUILD_IMAGE}" \
                            bash -ceu '
                                apt-get update >/dev/null
                                DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                    awscli >/dev/null

                                while IFS= read -r version; do
                                    [[ -n "$version" ]] || continue
                                    key="$R2_PREFIX/$version/linux-x64/manifest.json"

                                    if aws s3api head-object \
                                        --endpoint-url "$R2_ENDPOINT" \
                                        --bucket "$R2_BUCKET" \
                                        --key "$key" >/dev/null 2>&1; then
                                        echo "Already published: $version" >&2
                                    else
                                        echo "Missing: $version" >&2
                                        printf '%s\n' "$version"
                                    fi
                                done
                            ' < work/candidates.txt > work/versions.txt

                        echo "Versions queued: $(wc -l < work/versions.txt)"
                        cat work/versions.txt
                    '''
                }
            }
        }

        stage('Build and publish') {
            steps {
                script {
                    def versionsText = readFile('work/versions.txt').trim()
                    if (!versionsText) {
                        echo 'Nothing to build; R2 already contains all discovered releases.'
                        return
                    }

                    for (String version : versionsText.split('\\n')) {
                        version = version.trim()
                        if (!version) {
                            continue
                        }

                        stage("Chromium ${version}") {
                            withEnv(["TARGET_CHROMIUM_VERSION=${version}"]) {
                                withCredentials([
                                    usernamePassword(
                                        credentialsId: 'r2-credentials',
                                        usernameVariable: 'AWS_ACCESS_KEY_ID',
                                        passwordVariable: 'AWS_SECRET_ACCESS_KEY'
                                    )
                                ]) {
                                    sh '''#!/usr/bin/env bash
                                        set -euo pipefail

                                        VERSION="$TARGET_CHROMIUM_VERSION"
                                        HOST_UID="$(id -u)"
                                        HOST_GID="$(id -g)"

                                        echo "Building Chromium $VERSION"

                                        docker run --rm \
                                            --volumes-from "$(hostname)" \
                                            --workdir "${WORKSPACE}" \
                                            --env VERSION \
                                            --env HOST_UID \
                                            --env HOST_GID \
                                            --env CHROMIUM_GITILES \
                                            --env FFMPEG_GIT \
                                            --env NWJS_BUILD_SH \
                                            --env R2_PREFIX \
                                            --env R2_PUBLIC_BASE \
                                            "${BUILD_IMAGE}" \
                                            bash -ceu '
                                                export DEBIAN_FRONTEND=noninteractive
                                                apt-get update >/dev/null
                                                apt-get install -y --no-install-recommends \
                                                    build-essential ca-certificates curl git nasm yasm \
                                                    python3 pkg-config xz-utils binutils file >/dev/null

                                                WORK_DIR="work/$VERSION"
                                                OUT_DIR="out/$VERSION/linux-x64"
                                                rm -rf "$WORK_DIR" "$OUT_DIR"
                                                mkdir -p "$WORK_DIR" "$OUT_DIR"
                                                cd "$WORK_DIR"

                                                curl -fsSL \
                                                    "$CHROMIUM_GITILES/+/refs/tags/$VERSION/DEPS?format=TEXT" \
                                                    | base64 -d > DEPS

                                                FFMPEG_REV="$(python3 - <<"PY"
import re
from pathlib import Path

text = Path("DEPS").read_text()
pos = text.find("ffmpeg_revision")
if pos < 0:
    raise SystemExit("Could not find ffmpeg_revision in Chromium DEPS")

hashes = re.findall("[0-9a-f]{40}", text[pos:pos + 500])
if not hashes:
    raise SystemExit("Could not resolve ffmpeg_revision from Chromium DEPS")

print(hashes[0])
PY
                                                )"

                                                echo "FFmpeg revision: $FFMPEG_REV"
                                                git clone -q "$FFMPEG_GIT" ffmpeg
                                                cd ffmpeg
                                                git checkout -q "$FFMPEG_REV"

                                                curl -fsSL "$NWJS_BUILD_SH" -o /tmp/build-ffmpeg.sh
                                                chmod +x /tmp/build-ffmpeg.sh
                                                /tmp/build-ffmpeg.sh linux-x64

                                                cd "$WORKSPACE"
                                                install -Dm755 "$WORK_DIR/ffmpeg/libffmpeg.so" "$OUT_DIR/libffmpeg.so"
                                                file "$OUT_DIR/libffmpeg.so"
                                                readelf -h "$OUT_DIR/libffmpeg.so" | grep -q "DYN (Shared object file)"

                                                sha256sum "$OUT_DIR/libffmpeg.so" > "$OUT_DIR/libffmpeg.so.sha256"
                                                SHA256="$(cut -d" " -f1 "$OUT_DIR/libffmpeg.so.sha256")"
                                                PUBLIC_PATH="$R2_PREFIX/$VERSION/linux-x64"

                                                cat > "$OUT_DIR/manifest.json" <<EOF
{
  "chromium": "$VERSION",
  "ffmpeg_commit": "$FFMPEG_REV",
  "platform": "linux",
  "arch": "x64",
  "sha256": "$SHA256",
  "download_url": "$R2_PUBLIC_BASE/$PUBLIC_PATH/libffmpeg.so"
}
EOF

                                                chown -R "$HOST_UID:$HOST_GID" "$WORK_DIR" "$OUT_DIR"
                                            '

                                        cat "out/$VERSION/linux-x64/manifest.json"

                                        docker run --rm \
                                            --volumes-from "$(hostname)" \
                                            --workdir "${WORKSPACE}" \
                                            --env AWS_ACCESS_KEY_ID \
                                            --env AWS_SECRET_ACCESS_KEY \
                                            --env AWS_DEFAULT_REGION=auto \
                                            --env VERSION \
                                            --env R2_ENDPOINT \
                                            --env R2_BUCKET \
                                            --env R2_PREFIX \
                                            "${BUILD_IMAGE}" \
                                            bash -ceu '
                                                apt-get update >/dev/null
                                                DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                                    awscli >/dev/null

                                                SRC="out/$VERSION/linux-x64"
                                                DEST="s3://$R2_BUCKET/$R2_PREFIX/$VERSION/linux-x64"

                                                aws s3 cp "$SRC/libffmpeg.so" "$DEST/libffmpeg.so" \
                                                    --endpoint-url "$R2_ENDPOINT" \
                                                    --content-type application/octet-stream

                                                aws s3 cp "$SRC/libffmpeg.so.sha256" "$DEST/libffmpeg.so.sha256" \
                                                    --endpoint-url "$R2_ENDPOINT" \
                                                    --content-type text/plain

                                                # Publish the manifest last; its presence marks a complete build.
                                                aws s3 cp "$SRC/manifest.json" "$DEST/manifest.json" \
                                                    --endpoint-url "$R2_ENDPOINT" \
                                                    --content-type application/json \
                                                    --cache-control "public,max-age=300"
                                            '

                                        echo "Published: $R2_PUBLIC_BASE/$R2_PREFIX/$VERSION/linux-x64/"
                                    '''
                                }
                            }
                        }
                    }
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
            cleanWs(deleteDirs: true, notFailBuild: true)
        }
    }
}
