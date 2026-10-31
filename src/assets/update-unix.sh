#!/bin/sh
set -eu
parent_pid=$1
system=$2
source_path=$3
target_path=$4
attempt=0
while kill -0 "$parent_pid" 2>/dev/null; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 120 ] || exit 1
    sleep 1
done
if [ "$system" = darwin ]; then
    # Replacement is staged on the same filesystem for atomic renames and rollback.
    replace_script='set -eu
source_path=$1
target_path=$2
parent_dir=$(dirname "$target_path")
work=$(/usr/bin/mktemp -d "$parent_dir/.triplesense-update.XXXXXX")
/usr/bin/ditto "$source_path" "$work/TripleSense.app"
/bin/mv "$target_path" "$work/previous.app"
if /bin/mv "$work/TripleSense.app" "$target_path"; then
    /bin/rm -rf "$work"
else
    /bin/mv "$work/previous.app" "$target_path"
    exit 1
fi'
    if [ -w "$(dirname "$target_path")" ]; then
        /bin/sh -c "$replace_script" sh "$source_path" "$target_path" || true
    else
        # argv is escaped by AppleScript, rather than interpolating paths into code.
        /usr/bin/osascript - "$replace_script" "$source_path" "$target_path" <<'APPLESCRIPT' || true
on run argv
    set commandText to "/bin/sh -c " & quoted form of item 1 of argv & " sh " & quoted form of item 2 of argv & " " & quoted form of item 3 of argv
    do shell script commandText with administrator privileges
end run
APPLESCRIPT
    fi
    /usr/bin/open "$target_path"
else
    /usr/bin/pkexec /usr/bin/apt-get install --yes "$source_path" || true
    "$target_path" >/dev/null 2>&1 &
fi
