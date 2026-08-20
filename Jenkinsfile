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

                    [[ "${MIN_MAJOR}" =~ ^[0-9]+$ ]] || {
                        echo "MIN_MAJOR must be numeric" >&2
                        exit 1
                    }

                    if [[ -n "${CHROMIUM_VERSION}" ]]; then
                        [[ "${CHROMIUM_VERSION}" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$ ]] || {
                            echo "Invalid Chromium version: ${CHROMIUM_VERSION}" >&2
                            exit 1
                        }
                    elif [[ "${AUTO_DISCOVER}" != 'true' ]]; then
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
                        AUTO_DISCOVER="${AUTO_DISCOVER:-true}"

                        docker run --rm \
                            -v "$PWD:/workspace" \
                            -w /workspace \
                            -e CHROMIUM_VERSION="${CHROMIUM_VERSION}" \
                            -e AUTO_DISCOVER="${AUTO_DISCOVER}" \
                            -e MIN_MAJOR="${MIN_MAJOR}" \
                            -e CHROMIUM_SRC="${CHROMIUM_SRC}" \
                            "${BUILD_IMAGE}" \
                            bash -ceu '
                                apt-get update >/dev/null
                                DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                    ca-certificates git >/dev/null

                                if [[ -n "${CHROMIUM_VERSION}" ]]; then
                                    printf "%s\\n" "${CHROMIUM_VERSION}" > work/candidates.txt
                                    exit 0
                                fi

                                git ls-remote --tags --refs "${CHROMIUM_SRC}" \
                                    | awk "{print \\$2}" \
                                    | sed "s#refs/tags/##" \
                                    | grep -E "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$" \
                                    | awk -F. -v min="${MIN_MAJOR}" "\\$1 >= min" \
                                    | sort -Vu > work/candidates.txt
                            '

                        docker run --rm \
                            -v "$PWD:/workspace" \
                            -w /workspace \
                            -e AWS_ACCESS_KEY_ID \
                            -e AWS_SECRET_ACCESS_KEY \
                            -e AWS_DEFAULT_REGION=auto \
                            -e R2_ENDPOINT="${R2_ENDPOINT}" \
                            -e R2_BUCKET="${R2_BUCKET}" \
                            -e R2_PREFIX="${R2_PREFIX}" \
                            "${BUILD_IMAGE}" \
                            bash -ceu '
                                apt-get update >/dev/null
                                DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                    awscli >/dev/null

                                : > work/versions.txt

                                while IFS= read -r version; do
                                    [[ -n "$version" ]] || continue
                                    key="${R2_PREFIX}/${version}/linux-x64/manifest.json"

                                    if aws s3api head-object \
                                        --endpoint-url "${R2_ENDPOINT}" \
                                        --bucket "${R2_BUCKET}" \
                                        --key "$key" >/dev/null 2>&1; then
                                        echo "Already published: $version"
                                    else
                                        echo "Missing: $version"
                                        printf "%s\\n" "$version" >> work/versions.txt
                                    fi
                                done < work/candidates.txt

                                echo "Versions queued: $(wc -l < work/versions.txt)"
                                cat work/versions.txt
                            '
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

                    def versions = versionsText.split('\\n')

                    for (String version : versions) {
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

                                        VERSION="${TARGET_CHROMIUM_VERSION}"
                                        VERSION_DIR="out/${VERSION}/linux-x64"
                                        WORK_DIR="work/${VERSION}"
                                        mkdir -p "$VERSION_DIR" "$WORK_DIR"

                                        echo "Resolving FFmpeg revision for Chromium ${VERSION}"

                                        docker run --rm \
                                            -v "$PWD:/workspace" \
                                            -w /workspace \
                                            -e VERSION="$VERSION" \
                                            -e CHROMIUM_GITILES="${CHROMIUM_GITILES}" \
                                            "${BUILD_IMAGE}" \
                                            bash -ceu '
                                                apt-get update >/dev/null
                                                DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                                    ca-certificates curl python3 >/dev/null

                                                curl -fsSL \
                                                    "${CHROMIUM_GITILES}/+/refs/tags/${VERSION}/DEPS?format=TEXT" \
                                                    | base64 -d > "work/${VERSION}/DEPS"

                                                python3 - <<"PY"
import os
import re
from pathlib import Path

version = os.environ["VERSION"]
text = Path(f"work/{version}/DEPS").read_text()

pos = text.find("ffmpeg_revision")
if pos < 0:
    raise SystemExit("Could not find ffmpeg_revision in Chromium DEPS")

window = text[pos:pos + 500]
hashes = re.findall("[0-9a-f]{40}", window)
if not hashes:
    raise SystemExit("Could not resolve ffmpeg_revision from Chromium DEPS")

revision = hashes[0]
Path(f"work/{version}/ffmpeg-revision.txt").write_text(revision + chr(10))
print(revision)
PY
                                            '

                                        FFMPEG_REV="$(cat "$WORK_DIR/ffmpeg-revision.txt")"
                                        echo "FFmpeg revision: ${FFMPEG_REV}"

                                        docker run --rm \
                                            -v "$PWD:/workspace" \
                                            -w /workspace \
                                            -e VERSION="$VERSION" \
                                            -e FFMPEG_REV="$FFMPEG_REV" \
                                            -e FFMPEG_GIT="${FFMPEG_GIT}" \
                                            -e NWJS_BUILD_SH="${NWJS_BUILD_SH}" \
                                            "${BUILD_IMAGE}" \
                                            bash -ceu '
                                                export DEBIAN_FRONTEND=noninteractive
                                                apt-get update >/dev/null
                                                apt-get install -y --no-install-recommends \
                                                    build-essential ca-certificates curl git nasm yasm \
                                                    python3 pkg-config xz-utils binutils file >/dev/null

                                                rm -rf "work/${VERSION}/ffmpeg"
                                                git clone -q "${FFMPEG_GIT}" "work/${VERSION}/ffmpeg"
                                                cd "work/${VERSION}/ffmpeg"
                                                git checkout -q "${FFMPEG_REV}"

                                                curl -fsSL "${NWJS_BUILD_SH}" -o /tmp/build-ffmpeg.sh
                                                chmod +x /tmp/build-ffmpeg.sh
                                                /tmp/build-ffmpeg.sh linux-x64

                                                install -Dm755 libffmpeg.so \
                                                    "/workspace/out/${VERSION}/linux-x64/libffmpeg.so"
                                            '

                                        LIB="$VERSION_DIR/libffmpeg.so"
                                        test -s "$LIB"
                                        file "$LIB"
                                        readelf -h "$LIB" | grep -q 'DYN (Shared object file)'

                                        sha256sum "$LIB" | tee "$VERSION_DIR/libffmpeg.so.sha256"
                                        SHA256="$(cut -d' ' -f1 "$VERSION_DIR/libffmpeg.so.sha256")"
                                        PUBLIC_PATH="${R2_PREFIX}/${VERSION}/linux-x64"

                                        cat > "$VERSION_DIR/manifest.json" <<EOF
{
  "chromium": "${VERSION}",
  "ffmpeg_commit": "${FFMPEG_REV}",
  "platform": "linux",
  "arch": "x64",
  "sha256": "${SHA256}",
  "download_url": "${R2_PUBLIC_BASE}/${PUBLIC_PATH}/libffmpeg.so"
}
EOF

                                        docker run --rm \
                                            -v "$PWD:/workspace" \
                                            -w /workspace \
                                            -e AWS_ACCESS_KEY_ID \
                                            -e AWS_SECRET_ACCESS_KEY \
                                            -e AWS_DEFAULT_REGION=auto \
                                            -e VERSION="$VERSION" \
                                            -e R2_ENDPOINT="${R2_ENDPOINT}" \
                                            -e R2_BUCKET="${R2_BUCKET}" \
                                            -e R2_PREFIX="${R2_PREFIX}" \
                                            "${BUILD_IMAGE}" \
                                            bash -ceu '
                                                apt-get update >/dev/null
                                                DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                                    awscli >/dev/null

                                                SRC="out/${VERSION}/linux-x64"
                                                DEST="s3://${R2_BUCKET}/${R2_PREFIX}/${VERSION}/linux-x64"

                                                aws s3 cp "${SRC}/libffmpeg.so" "${DEST}/libffmpeg.so" \
                                                    --endpoint-url "${R2_ENDPOINT}" \
                                                    --content-type application/octet-stream

                                                aws s3 cp "${SRC}/libffmpeg.so.sha256" "${DEST}/libffmpeg.so.sha256" \
                                                    --endpoint-url "${R2_ENDPOINT}" \
                                                    --content-type text/plain

                                                # Manifest is written last and acts as the atomic marker
                                                # that this version is fully published.
                                                aws s3 cp "${SRC}/manifest.json" "${DEST}/manifest.json" \
                                                    --endpoint-url "${R2_ENDPOINT}" \
                                                    --content-type application/json \
                                                    --cache-control "public,max-age=300"
                                            '

                                        echo "Published: ${R2_PUBLIC_BASE}/${PUBLIC_PATH}/"
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
                archiveArtifacts artifacts: 'out/**/manifest.json,out/**/libffmpeg.so.sha256', allowEmptyArchive: true, fingerprint: true
            }
        }
    }

    post {
        always {
            cleanWs(deleteDirs: true, notFailBuild: true)
        }
    }
}
