pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20', artifactNumToKeepStr: '10'))
        timeout(time: 90, unit: 'MINUTES')
    }

    parameters {
        string(
            name: 'CHROMIUM_VERSION',
            defaultValue: '150.0.7871.230',
            description: 'Exact Chromium version/tag to build against'
        )
    }

    environment {
        BUILD_IMAGE = 'ubuntu:24.04'
        FFMPEG_GIT = 'https://chromium.googlesource.com/chromium/third_party/ffmpeg.git'
        CHROMIUM_GITILES = 'https://chromium.googlesource.com/chromium/src'
        NWJS_BUILD_SH = 'https://raw.githubusercontent.com/nwjs-ffmpeg-prebuilt/nwjs-ffmpeg-prebuilt/master/build.sh'
    }

    stages {
        stage('Validate') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail
                    [[ "${CHROMIUM_VERSION}" =~ ^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$ ]] || {
                        echo "Invalid Chromium version: ${CHROMIUM_VERSION}" >&2
                        exit 1
                    }
                '''
            }
        }

        stage('Resolve FFmpeg revision') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail
                    rm -rf work out
                    mkdir -p work out

                    docker run --rm \
                        -v "$PWD:/workspace" \
                        -w /workspace \
                        -e CHROMIUM_VERSION="${CHROMIUM_VERSION}" \
                        "${BUILD_IMAGE}" \
                        bash -ceu '
                            apt-get update >/dev/null
                            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                                ca-certificates curl python3 >/dev/null

                            curl -fsSL \
                                "https://chromium.googlesource.com/chromium/src/+/refs/tags/${CHROMIUM_VERSION}/DEPS?format=TEXT" \
                                | base64 -d > work/DEPS

                            python3 - <<"PY"
import re
from pathlib import Path

text = Path("work/DEPS").read_text()

# Chromium DEPS keeps the ffmpeg checkout as a git dependency. Restrict the
# search to the dependency entry so we do not accidentally pick another hash.
m = re.search(
    r"['\\\"]src/third_party/ffmpeg['\\\"]\\s*:\\s*.*?@['\\\"]?([0-9a-f]{40})",
    text,
    re.S,
)
if not m:
    # Some DEPS revisions format the URL/hash across helper expressions.
    p = text.find("src/third_party/ffmpeg")
    if p < 0:
        raise SystemExit("Could not find src/third_party/ffmpeg in Chromium DEPS")
    window = text[p:p + 1500]
    hashes = re.findall(r"[0-9a-f]{40}", window)
    if not hashes:
        raise SystemExit("Could not resolve FFmpeg revision from Chromium DEPS")
    rev = hashes[0]
else:
    rev = m.group(1)

Path("work/ffmpeg-revision.txt").write_text(rev + "\\n")
print(rev)
PY
                        '

                    echo "Resolved FFmpeg revision: $(cat work/ffmpeg-revision.txt)"
                '''
            }
        }

        stage('Build') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail

                    docker run --rm \
                        -v "$PWD:/workspace" \
                        -w /workspace \
                        -e CHROMIUM_VERSION="${CHROMIUM_VERSION}" \
                        -e FFMPEG_GIT="${FFMPEG_GIT}" \
                        -e NWJS_BUILD_SH="${NWJS_BUILD_SH}" \
                        "${BUILD_IMAGE}" \
                        bash -ceu '
                            export DEBIAN_FRONTEND=noninteractive
                            apt-get update >/dev/null
                            apt-get install -y --no-install-recommends \
                                build-essential \
                                ca-certificates \
                                curl \
                                git \
                                nasm \
                                yasm \
                                python3 \
                                pkg-config \
                                xz-utils \
                                binutils \
                                file >/dev/null

                            FFMPEG_REV="$(cat work/ffmpeg-revision.txt)"
                            rm -rf work/ffmpeg
                            git clone -q "${FFMPEG_GIT}" work/ffmpeg
                            cd work/ffmpeg
                            git checkout -q "${FFMPEG_REV}"

                            curl -fsSL "${NWJS_BUILD_SH}" -o /tmp/build-ffmpeg.sh
                            chmod +x /tmp/build-ffmpeg.sh

                            /tmp/build-ffmpeg.sh linux-x64

                            install -Dm755 libffmpeg.so /workspace/out/libffmpeg.so
                        '
                '''
            }
        }

        stage('Verify') {
            steps {
                sh '''#!/usr/bin/env bash
                    set -euo pipefail

                    test -s out/libffmpeg.so
                    file out/libffmpeg.so

                    if ! readelf -h out/libffmpeg.so | grep -q 'DYN (Shared object file)'; then
                        echo 'libffmpeg.so is not an ELF shared object' >&2
                        exit 1
                    fi

                    # The symbol that prompted this builder; keeping this check also catches
                    # accidentally building an older/incompatible FFmpeg revision.
                    if ! nm -D out/libffmpeg.so | grep -q 'av_dynamic_hdr_smpte2094_app5_to_t35'; then
                        echo 'Required symbol av_dynamic_hdr_smpte2094_app5_to_t35 is missing' >&2
                        exit 1
                    fi

                    sha256sum out/libffmpeg.so | tee out/libffmpeg.so.sha256

                    cat > out/manifest.json <<EOF
                    {
                      "chromium": "${CHROMIUM_VERSION}",
                      "ffmpeg_commit": "$(cat work/ffmpeg-revision.txt)",
                      "platform": "linux",
                      "arch": "x64",
                      "sha256": "$(cut -d' ' -f1 out/libffmpeg.so.sha256)"
                    }
                    EOF

                    cat out/manifest.json
                '''
            }
        }

        stage('Archive') {
            steps {
                archiveArtifacts artifacts: 'out/*', fingerprint: true
            }
        }
    }

    post {
        always {
            cleanWs(deleteDirs: true, notFailBuild: true)
        }
    }
}
