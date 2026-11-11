#!/bin/sh
# Verify and install an Arkanine Offline bundle. Nothing is downloaded. See docs/bundle.md.
#
#   install.sh [--signers FILE] [--verify-only] [BUNDLE_DIR]
#
# BUNDLE_DIR defaults to the directory holding this script. The bundle is trusted only if
# SHA256SUMS is signed by a key in FILE, an SSH allowed-signers file. Without --signers, the
# key of the existing installation in ARKANINE_HOME (default ~/arkanine) is used.
set -eu

PRINCIPAL=release@arkanine
NAMESPACE=arkanine-bundle
ARKANINE_HOME=${ARKANINE_HOME:-$HOME/arkanine}

die() {
	echo "install.sh: $*" >&2
	exit 1
}

reject() {
	die "$*
Do not install this bundle."
}

signers=""
verify_only=false
bundle=""
while [ $# -gt 0 ]; do
	case $1 in
	--signers)
		[ $# -ge 2 ] || die "--signers needs a file"
		signers=$2
		shift 2
		;;
	--verify-only)
		verify_only=true
		shift
		;;
	-h | --help)
		sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
		exit 0
		;;
	-*) die "unknown option $1" ;;
	*)
		[ -z "$bundle" ] || die "give one bundle directory"
		bundle=$1
		shift
		;;
	esac
done
[ -n "$bundle" ] || bundle=$(dirname "$0")
bundle=$(cd "$bundle" && pwd) || die "no bundle directory at $bundle"

if [ -z "$signers" ]; then
	signers=$ARKANINE_HOME/keys/allowed_signers
	[ -f "$signers" ] || die "no trusted public key: there is no installation in $ARKANINE_HOME.
Pass --signers with the Arkanine public key you received separately from the bundle
(see docs/bundle.md). The key inside a bundle can't vouch for that bundle."
fi
[ -f "$signers" ] || die "no public key file at $signers"
signers=$(cd "$(dirname "$signers")" && pwd)/$(basename "$signers")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

verify() {
	cd "$bundle"
	[ -f SHA256SUMS ] && [ -f SHA256SUMS.sig ] ||
		reject "$bundle is not an Arkanine bundle: SHA256SUMS or SHA256SUMS.sig is missing"

	ssh-keygen -Y verify -f "$signers" -I "$PRINCIPAL" -n "$NAMESPACE" -s SHA256SUMS.sig \
		<SHA256SUMS >"$work/signature" 2>&1 ||
		reject "SHA256SUMS is not signed by a trusted Arkanine key.
$(cat "$work/signature")"

	# The signed list must be well formed, and name every file present and no others.
	if grep -Ev '^[0-9a-f]{64}  [A-Za-z0-9_.+-][A-Za-z0-9_.+/-]*$' SHA256SUMS | grep -q . ||
		grep -Eq '(^|/)\.\.(/|$)' SHA256SUMS; then
		reject "SHA256SUMS has a malformed line"
	fi
	[ -z "$(find . ! -type d ! -type f)" ] || reject "the bundle holds something other than plain files"
	sed 's/^[0-9a-f]*  //' SHA256SUMS | sort >"$work/listed"
	find . -type f ! -path ./SHA256SUMS ! -path ./SHA256SUMS.sig | sed 's|^\./||' | sort >"$work/present"
	if ! cmp -s "$work/listed" "$work/present"; then
		reject "the bundle's files don't match SHA256SUMS:
$(diff "$work/listed" "$work/present" | grep '^[<>]' | sed 's/^</  missing:/; s/^>/  unexpected:/')"
	fi

	if command -v sha256sum >/dev/null 2>&1; then
		check="sha256sum -c"
	else
		check="shasum -a 256 -c"
	fi
	$check SHA256SUMS >"$work/checksums" 2>&1 ||
		reject "files in the bundle don't match their checksums.
$(grep -v ': OK$' "$work/checksums")"
	cd - >/dev/null
}

verify
echo "Verified $bundle"
if $verify_only; then
	exit 0
fi

# Signed with everything else: ARKANINE_VERSION and ARKANINE_TIER.
. "$bundle/bundle.env"
command -v docker >/dev/null 2>&1 || die "Docker with Compose is needed; see docs/bundle.md"

for image in "$bundle"/images/*.tar; do
	echo "Loading $(basename "$image")"
	docker load -q -i "$image" >/dev/null
done

mkdir -p "$ARKANINE_HOME/bin" "$ARKANINE_HOME/keys"
rm -f "$ARKANINE_HOME"/compose.*.yaml
cp "$bundle/compose.yaml" "$bundle/compose.$ARKANINE_TIER.yaml" "$ARKANINE_HOME/"
# Kept so later bundles are verified by this installer and key, not by their own.
cp "$bundle/install.sh" "$ARKANINE_HOME/bin/install.sh"
cp "$bundle/keys/allowed_signers" "$ARKANINE_HOME/keys/allowed_signers"
rm -rf "$ARKANINE_HOME/models"
mkdir "$ARKANINE_HOME/models"
if [ -d "$bundle/models" ]; then
	echo "Copying model files"
	cp -R "$bundle/models/." "$ARKANINE_HOME/models/"
fi

# Passwords are generated at first install and kept by later ones.
env_file=$ARKANINE_HOME/.env
previous() {
	[ -f "$env_file" ] && sed -n "s/^$1=//p" "$env_file" | tail -n 1
}
random() {
	od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}
admin_username=$(previous ARKANINE_ADMIN_USERNAME) || true
admin_password=$(previous ARKANINE_ADMIN_PASSWORD) || true
db_password=$(previous ARKANINE_DB_PASSWORD) || true
api_port=$(previous API_PORT) || true
(
	umask 077
	cat >"$env_file.new" <<EOF
# Written by install.sh. The passwords were generated at first install; keep this file safe.
COMPOSE_FILE=compose.yaml:compose.$ARKANINE_TIER.yaml
ARKANINE_VERSION=$ARKANINE_VERSION
ARKANINE_ADMIN_USERNAME=${admin_username:-admin}
ARKANINE_ADMIN_PASSWORD=${admin_password:-$(random)}
ARKANINE_DB_PASSWORD=${db_password:-$(random)}
API_PORT=${api_port:-8000}
EOF
)
mv "$env_file.new" "$env_file"

echo "Starting Arkanine $ARKANINE_VERSION ($ARKANINE_TIER)"
cd "$ARKANINE_HOME"
docker compose up --detach --wait --remove-orphans
echo "Arkanine is running at http://localhost:${API_PORT:-${api_port:-8000}}."
echo "Sign in as the administrator with the username and password in $env_file."
