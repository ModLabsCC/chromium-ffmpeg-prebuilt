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
        AWS_IMAGE = 'amazon/aws-cli:latest'

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
                                        | grep -E "^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$" \
                                        | awk -F. -v min="$MIN_MAJOR" "\\$1 >= min" \
                                        | sort -Vu
                                ' > work/candidates.txt
                        fi

                        : > work/versions.txt
                        while IFS= read -r version; do
                            [[ -n "$version" ]] || continue
                            key="$R2_PREFIX/$version/linux-x64/manifest.json"

                            if docker run --rm \
                                --env AWS_ACCESS_KEY_ID \
                                --env AWS_SECRET_ACCESS_KEY \
                                --env AWS_DEFAULT_REGION=auto \
                                "${AWS_IMAGE}" \
                                s3api head-object \
                                    --endpoint-url "$R2_ENDPOINT" \
                                    --bucket "$R2_BUCKET" \
                                    --key "$key" >/dev/null 2>&1; then
                                echo "Already published: $version"
                            else
                                echo "Missing: $version"
                                printf '%s\n' "$version" >> work/versions.txt
                            fi
                        done < work/candidates.txt

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

                    HOST_UID="$(id -u)"
                    HOST_GID="$(id -g)"

                    docker run --rm \
                        --volumes-from "$(hostname)" \
                        --workdir "${WORKSPACE}" \
                        --env HOST_UID \
                        --env HOST_GID \
                        --env CHROMIUM_GITILES \
                        "${BUILD_IMAGE}" \
                        bash -ceu '
                            export DEBIAN_FRONTEND=noninteractive
                            apt-get update >/dev/null
                            apt-get install -y --no-install-recommends \
                                ca-certificates curl python3 >/dev/null

                            : > work/mappings.tsv

                            while IFS= read -r version; do
                                [[ -n "$version" ]] || continue
                                echo "Resolving FFmpeg revision for Chromium $version" >&2

                                deps="$(curl -fsSL "$CHROMIUM_GITILES/+/refs/tags/$version/DEPS?format=TEXT" | base64 -d)"
                                revision="$(DEPS_TEXT="$deps" python3 - <<"PY"
import os
import re

text = os.environ["DEPS_TEXT"]
pos = text.find("ffmpeg_revision")
if pos < 0:
    raise SystemExit("Could not find ffmpeg_revision in Chromium DEPS")

hashes = re.findall("[0-9a-f]{40}", text[pos:pos + 500])
if not hashes:
    raise SystemExit("Could not resolve ffmpeg_revision from Chromium DEPS")

print(hashes[0])
PY
                                )"

                                printf "%s\t%s\n" "$version" "$revision" >> work/mappings.tsv
                            done < work/versions.txt

                            chown "$HOST_UID:$HOST_GID" work/mappings.tsv
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
                    )
                ]) {
                    sh '''#!/usr/bin/env bash
                        set -euo pipefail

                        if [[ ! -s work/revisions.txt ]]; then
                            echo 'Nothing to build; R2 already contains all discovered releases.'
                            exit 0
                        fi

                        HOST_UID="$(id -u)"
                        HOST_GID="$(id -g)"

                        while IFS= read -r revision; do
                            [[ -n "$revision" ]] || continue

                            versions_file="work/versions-$revision.txt"
                            awk -F '	' -v revision="$revision" '$2 == revision { print $1 }' \
                                work/mappings.tsv > "$versions_file"

                            version_count="$(wc -l < "$versions_file")"
                            echo "Building FFmpeg $revision once for $version_count Chromium version(s)"

                            BUILD_DIR="work/build-$revision"
                            rm -rf "$BUILD_DIR"

                            docker run --rm \
                                --volumes-from "$(hostname)" \
                                --workdir "${WORKSPACE}" \
                                --env FFMPEG_REV="$revision" \
                                --env HOST_UID \
                                --env HOST_GID \
                                --env FFMPEG_GIT \
                                --env NWJS_BUILD_SH \
                                "${BUILD_IMAGE}" \
                                bash -ceu '
                                    export DEBIAN_FRONTEND=noninteractive
                                    apt-get update >/dev/null
                                    apt-get install -y --no-install-recommends \
                                        build-essential ca-certificates curl git nasm yasm \
                                        python3 pkg-config xz-utils binutils file >/dev/null

                                    BUILD_DIR="work/build-$FFMPEG_REV"
                                    rm -rf "$BUILD_DIR"
                                    mkdir -p "$BUILD_DIR"
                                    cd "$BUILD_DIR"

                                    git clone -q "$FFMPEG_GIT" ffmpeg
                                    cd ffmpeg
                                    git checkout -q "$FFMPEG_REV"

                                    curl -fsSL "$NWJS_BUILD_SH" -o /tmp/build-ffmpeg.sh
                                    chmod +x /tmp/build-ffmpeg.sh
                                    /tmp/build-ffmpeg.sh linux-x64

                                    cd "$WORKSPACE"
                                    install -Dm755 "$BUILD_DIR/ffmpeg/libffmpeg.so" "$BUILD_DIR/libffmpeg.so"
                                    file "$BUILD_DIR/libffmpeg.so"
                                    readelf -h "$BUILD_DIR/libffmpeg.so" | grep -q "DYN (Shared object file)"
                                    sha256sum "$BUILD_DIR/libffmpeg.so" > "$BUILD_DIR/libffmpeg.so.sha256"

                                    chown -R "$HOST_UID:$HOST_GID" "$BUILD_DIR"
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

                                # Manifest goes last and acts as the atomic completion marker.
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

                            # Only tiny manifests/checksums remain locally. The source tree,
                            # object files, and shared binary are discarded after each unique revision.
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
            cleanWs(deleteDirs: true, notFailBuild: true)
        }
    }
}
