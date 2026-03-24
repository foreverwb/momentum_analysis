#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
DEFAULT_DOWNLOADS_DIR="${HOME}/Downloads"
DEFAULT_W="80"
DEFAULT_API_BASE="${MOMENTUM_API_BASE_URL:-http://127.0.0.1:8000}"

# Keep these lists empty by default.
# Add files only when you want to import the corresponding provider data.
finviz_list=()

mc_list=(
  "${DEFAULT_DOWNLOADS_DIR}/MC_w_80_1_24-03_08_38_N49.json"
)

# Holdings import target passed to `finviz/mc -s`.
# Leave empty to infer from file name.
# Example: target="XLK,IGV,SOXX,SMH"
# target="XLC,XLE,XLF,XLK,XLV,XLY,SOXX,SMH,IGV,XSD,XTL"
target="XTL"

# Known stock symbols that may be missing provider data.
# These symbols will be passed to `Actualiser holdings --exclude-symbols`
# so missing fresh imports for them won't block holdings refresh.
# Example: exclude_symbols="UI"
exclude_symbols="UI"

SOURCE_VALUE=""
W_VALUE="$DEFAULT_W"
API_BASE="$DEFAULT_API_BASE"
DATE_VALUE=""
SOURCE_SET=0
W_SET=0

FINVIZ_IMPORTED=0
MC_IMPORTED=0
TOTAL_IMPORTED=0
REFRESH_ALL_ETFS=0
etf_refresh_symbols=()
holdings_refresh_symbols=()
excluded_holdings_refresh_targets=()

usage() {
  cat <<'EOF'
Usage:
  ./import.sh --source ibkr --w 75
  ./import.sh source=futu w=85

Options:
  --source, -s   ibkr | futu
  --w, -w        75 | 80 | 85
  --date, -d     import date, format: YYYY-MM-DD
  --api-base     backend API base url for Actualiser
  --help, -h     show this help

Notes:
  - finviz and mc imports run first.
  - if source is provided, the script also submits Actualiser jobs.
  - weight-specific files are filtered by w; ETF-level files always run.
EOF
}

info() {
  printf '[INFO] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1" >&2
}

die() {
  printf '[ERROR] %s\n' "$1" >&2
  exit 1
}

to_upper() {
  printf '%s' "$1" | tr '[:lower:]' '[:upper:]'
}

is_valid_source() {
  case "$1" in
    ibkr|futu) return 0 ;;
    *) return 1 ;;
  esac
}

is_valid_weight() {
  case "$1" in
    75|80|85) return 0 ;;
    *) return 1 ;;
  esac
}

is_sector_symbol() {
  case "$1" in
    XLB|XLC|XLE|XLF|XLI|XLK|XLP|XLU|XLV|XLY) return 0 ;;
    *) return 1 ;;
  esac
}

append_unique_etf_symbol() {
  local value="$1"
  local item
  if [[ ${#etf_refresh_symbols[@]} -gt 0 ]]; then
    for item in "${etf_refresh_symbols[@]}"; do
      if [[ "$item" == "$value" ]]; then
        return 0
      fi
    done
  fi
  etf_refresh_symbols+=("$value")
}

append_unique_holdings_symbol() {
  local value="$1"
  local item
  if [[ ${#holdings_refresh_symbols[@]} -gt 0 ]]; then
    for item in "${holdings_refresh_symbols[@]}"; do
      if [[ "$item" == "$value" ]]; then
        return 0
      fi
    done
  fi
  holdings_refresh_symbols+=("$value")
}

append_unique_excluded_holdings_target() {
  local value="$1"
  local item
  if [[ ${#excluded_holdings_refresh_targets[@]} -gt 0 ]]; then
    for item in "${excluded_holdings_refresh_targets[@]}"; do
      if [[ "$item" == "$value" ]]; then
        return 0
      fi
    done
  fi
  excluded_holdings_refresh_targets+=("$value")
}

append_csv_to_etf_symbols() {
  local csv="$1"
  local old_ifs="$IFS"
  local symbol
  IFS=','
  for symbol in $csv; do
    [[ -n "$symbol" ]] && append_unique_etf_symbol "$symbol"
  done
  IFS="$old_ifs"
}

append_csv_to_holdings_symbols() {
  local csv="$1"
  local old_ifs="$IFS"
  local symbol
  IFS=','
  for symbol in $csv; do
    [[ -n "$symbol" ]] && append_unique_holdings_symbol "$symbol"
  done
  IFS="$old_ifs"
}

csv_contains_symbol() {
  local csv="$1"
  local needle
  local token
  needle="$(to_upper "$2")"
  [[ -n "$needle" ]] || return 1

  local old_ifs="$IFS"
  IFS=','
  for token in $csv; do
    token="$(to_upper "$(printf '%s' "$token" | tr -d '[:space:]')")"
    if [[ -n "$token" && "$token" == "$needle" ]]; then
      IFS="$old_ifs"
      return 0
    fi
  done
  IFS="$old_ifs"
  return 1
}

track_excluded_holdings_targets_from_output() {
  local output="$1"
  local line etf missing_csv old_ifs symbol should_exclude

  [[ -n "$exclude_symbols" ]] || return 0

  while IFS= read -r line; do
    if [[ "$line" =~ ^\[([A-Z0-9.\-]+)\][[:space:]]提示:\ 覆盖范围缺失[[:space:]][0-9]+[[:space:]]个标的:\ (.+)$ ]]; then
      etf="${BASH_REMATCH[1]}"
      missing_csv="${BASH_REMATCH[2]}"
      should_exclude=1

      old_ifs="$IFS"
      IFS=','
      for symbol in $missing_csv; do
        symbol="$(to_upper "$(printf '%s' "$symbol" | tr -d '[:space:]')")"
        if [[ -z "$symbol" ]]; then
          continue
        fi
        if ! csv_contains_symbol "$exclude_symbols" "$symbol"; then
          should_exclude=0
          break
        fi
      done
      IFS="$old_ifs"

      if [[ "$should_exclude" -eq 1 ]]; then
        info "allow missing coverage symbols during holdings refresh due to exclude_symbols: $etf <- $missing_csv"
      fi
    fi
  done <<< "$output"
}

join_symbols() {
  local joined=""
  local item
  for item in "$@"; do
    if [[ -z "$joined" ]]; then
      joined="$item"
    else
      joined="$joined,$item"
    fi
  done
  printf '%s\n' "$joined"
}

extract_file_weight() {
  local base
  base="$(basename "$1")"
  if [[ "$base" =~ -w([0-9]+)_ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  fi
}

detect_import_type() {
  local base
  base="$(basename "$1")"
  base="$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')"

  if [[ "$base" == *etfs* ]]; then
    printf 'etf\n'
  else
    printf 'holdings\n'
  fi
}

extract_group_key() {
  local base
  base="$(basename "$1")"
  base="${base%.*}"

  case "$base" in
    MC_*) base="${base#MC_}" ;;
    Finviz_*) base="${base#Finviz_}" ;;
  esac

  if [[ "$base" =~ ^(.+)-w[0-9]+_ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi

  if [[ "$base" =~ ^(.+)_[0-9]{2}-[0-9]{2}_.+$ ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
    return 0
  fi

  printf '%s\n' "$base"
}

expand_group_token() {
  local token upper candidate
  token="$1"
  upper="$(to_upper "$token")"

  if is_sector_symbol "$upper"; then
    printf '%s\n' "$upper"
    return 0
  fi

  if [[ ${#upper} -eq 1 ]]; then
    candidate="XL$upper"
    if is_sector_symbol "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  printf '%s\n' "$upper"
}

extract_target_csv() {
  local group_key="$1"
  local old_ifs="$IFS"
  local token symbol csv=""
  local parts=()

  if [[ -z "$group_key" || "$group_key" == "ETFS" ]]; then
    printf '\n'
    return 0
  fi

  IFS='_'
  read -r -a parts <<< "$group_key"
  IFS="$old_ifs"

  for token in "${parts[@]}"; do
    [[ -z "$token" ]] && continue
    symbol="$(expand_group_token "$token")"
    case ",$csv," in
      *,"$symbol",*) ;;
      *)
        if [[ -z "$csv" ]]; then
          csv="$symbol"
        else
          csv="$csv,$symbol"
        fi
        ;;
    esac
  done

  printf '%s\n' "$csv"
}

select_python() {
  if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$BACKEND_DIR/.venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi

  return 1
}

resolve_provider_file() {
  local provider="$1"
  local raw_file="$2"
  local provider_dir=""
  local candidate

  case "$provider" in
    finviz) provider_dir="$DEFAULT_DOWNLOADS_DIR" ;;
    mc) provider_dir="$DEFAULT_DOWNLOADS_DIR" ;;
  esac

  if [[ -f "$raw_file" ]]; then
    printf '%s\n' "$raw_file"
    return 0
  fi

  if [[ -f "$PROJECT_ROOT/$raw_file" ]]; then
    printf '%s\n' "$PROJECT_ROOT/$raw_file"
    return 0
  fi

  if [[ -f "$BACKEND_DIR/$raw_file" ]]; then
    printf '%s\n' "$BACKEND_DIR/$raw_file"
    return 0
  fi

  candidate="$provider_dir/$raw_file"
  if [[ -f "$candidate" ]]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  return 1
}

run_cli_capture() {
  (
    cd "$BACKEND_DIR"
    "$CLI_PYTHON" -m app.cli "$@"
  ) 2>&1
}

import_provider_files() {
  local provider="$1"
  shift

  local files=("$@")
  local file file_weight import_type group_key resolved_target output resolved_file
  local imported_count=0

  if [[ ${#files[@]} -eq 0 ]]; then
    info "skip $provider import: ${provider}_list is empty"
    if [[ "$provider" == "finviz" ]]; then
      FINVIZ_IMPORTED=0
    else
      MC_IMPORTED=0
    fi
    return 0
  fi

  for file in "${files[@]}"; do
    file_weight="$(extract_file_weight "$file")"
    if [[ -n "$file_weight" && "$file_weight" != "$W_VALUE" ]]; then
      info "skip $provider file for w=$W_VALUE: $file"
      continue
    fi

    import_type="$(detect_import_type "$file")"
    group_key="$(extract_group_key "$file")"
    resolved_target=""
    if [[ "$import_type" == "holdings" ]]; then
      if [[ -n "$target" ]]; then
        resolved_target="$target"
      else
        resolved_target="$(extract_target_csv "$group_key")"
      fi
      if [[ -z "$resolved_target" ]]; then
        die "unable to infer target from holdings file name: $file"
      fi
    fi

    if [[ "$import_type" == "etf" ]]; then
      info "import $provider etf file: $file"
    else
      info "import $provider holdings file: $file -> target=$resolved_target, w=$W_VALUE"
    fi

    if ! resolved_file="$(resolve_provider_file "$provider" "$file")"; then
      warn "missing $provider file, skipped: $file"
      continue
    fi

    local cmd=("$provider" "etfs")
    if [[ -n "$DATE_VALUE" ]]; then
      cmd+=("-d" "$DATE_VALUE")
    fi
    if [[ -n "$resolved_target" ]]; then
      cmd+=("-s" "$resolved_target" "-w" "$W_VALUE")
    fi
    cmd+=("-f" "$resolved_file")

    if output="$(run_cli_capture "${cmd[@]}")"; then
      printf '%s\n' "$output"
      imported_count=$((imported_count + 1))
      TOTAL_IMPORTED=$((TOTAL_IMPORTED + 1))
      track_excluded_holdings_targets_from_output "$output"

      if [[ "$import_type" == "etf" ]]; then
        REFRESH_ALL_ETFS=1
      fi
      if [[ -n "$resolved_target" ]]; then
        append_csv_to_etf_symbols "$resolved_target"
        append_csv_to_holdings_symbols "$resolved_target"
      fi
    else
      printf '%s\n' "$output" >&2
      die "$provider import failed: $resolved_file"
    fi
  done

  if [[ "$provider" == "finviz" ]]; then
    FINVIZ_IMPORTED=$imported_count
  else
    MC_IMPORTED=$imported_count
  fi
}

submit_actualiser_jobs() {
  local output
  local etfs_csv holdings_csv
  local filtered_holdings_symbols=()
  local symbol skip_symbol excluded_target
  local holdings_cmd_extra=()

  if [[ -z "$SOURCE_VALUE" ]]; then
    info "source is empty, skip Actualiser"
    return 0
  fi

  if [[ "$TOTAL_IMPORTED" -eq 0 ]]; then
    warn "no files imported, skip Actualiser"
    return 0
  fi

  etfs_csv=""
  holdings_csv=""
  if [[ ${#etf_refresh_symbols[@]} -gt 0 ]]; then
    etfs_csv="$(join_symbols "${etf_refresh_symbols[@]}")"
  fi
  if [[ ${#holdings_refresh_symbols[@]} -gt 0 ]]; then
    for symbol in "${holdings_refresh_symbols[@]}"; do
      skip_symbol=0
      if [[ ${#excluded_holdings_refresh_targets[@]} -gt 0 ]]; then
        for excluded_target in "${excluded_holdings_refresh_targets[@]}"; do
          if [[ "$symbol" == "$excluded_target" ]]; then
            skip_symbol=1
            break
          fi
        done
      fi
      if [[ "$skip_symbol" -eq 0 ]]; then
        filtered_holdings_symbols+=("$symbol")
      fi
    done
  fi
  if [[ ${#filtered_holdings_symbols[@]} -gt 0 ]]; then
    holdings_csv="$(join_symbols "${filtered_holdings_symbols[@]}")"
  fi

  local etf_cmd=("Actualiser" "etfs" "--source" "$SOURCE_VALUE" "--api-base" "$API_BASE")
  if [[ "$REFRESH_ALL_ETFS" -eq 0 ]]; then
    if [[ -z "$etfs_csv" ]]; then
      warn "no etf symbols inferred, skip Actualiser etfs"
    else
      etf_cmd+=("-s" "$etfs_csv")
    fi
  fi

  if [[ "$REFRESH_ALL_ETFS" -eq 1 || -n "$etfs_csv" ]]; then
    info "submit Actualiser etfs, source=$SOURCE_VALUE"
    if output="$(run_cli_capture "${etf_cmd[@]}")"; then
      printf '%s\n' "$output"
    else
      printf '%s\n' "$output" >&2
      die "Actualiser etfs failed"
    fi
  fi

  if [[ -z "$holdings_csv" ]]; then
    warn "no coverage files matched w=$W_VALUE, skip Actualiser holdings"
    return 0
  fi

  if [[ -n "$exclude_symbols" ]]; then
    holdings_cmd_extra+=("--exclude-symbols" "$exclude_symbols")
  fi

  info "submit Actualiser holdings, source=$SOURCE_VALUE, w=$W_VALUE, etfs=$holdings_csv"
  if output="$(run_cli_capture "Actualiser" "holdings" "-s" "$holdings_csv" "-w" "$W_VALUE" "--source" "$SOURCE_VALUE" "--api-base" "$API_BASE" "${holdings_cmd_extra[@]}")"; then
    printf '%s\n' "$output"
  else
    printf '%s\n' "$output" >&2
    die "Actualiser holdings failed"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source|-s)
      shift
      [[ $# -gt 0 ]] || die "missing value for --source"
      SOURCE_VALUE="$1"
      SOURCE_SET=1
      ;;
    --w|-w)
      shift
      [[ $# -gt 0 ]] || die "missing value for --w"
      W_VALUE="$1"
      W_SET=1
      ;;
    --date|-d)
      shift
      [[ $# -gt 0 ]] || die "missing value for --date"
      DATE_VALUE="$1"
      ;;
    --api-base)
      shift
      [[ $# -gt 0 ]] || die "missing value for --api-base"
      API_BASE="$1"
      ;;
    source=*)
      SOURCE_VALUE="${1#source=}"
      SOURCE_SET=1
      ;;
    w=*)
      W_VALUE="${1#w=}"
      W_SET=1
      ;;
    ibkr|futu)
      if [[ "$SOURCE_SET" -eq 1 ]]; then
        die "source specified more than once"
      fi
      SOURCE_VALUE="$1"
      SOURCE_SET=1
      ;;
    75|80|85)
      if [[ "$W_SET" -eq 1 ]]; then
        die "w specified more than once"
      fi
      W_VALUE="$1"
      W_SET=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
  shift
done

if [[ -n "$SOURCE_VALUE" ]] && ! is_valid_source "$SOURCE_VALUE"; then
  die "source must be ibkr or futu"
fi

if ! is_valid_weight "$W_VALUE"; then
  die "w must be 75, 80 or 85"
fi

if [[ -n "$DATE_VALUE" && ! "$DATE_VALUE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  die "date must use YYYY-MM-DD"
fi

[[ -d "$BACKEND_DIR" ]] || die "backend directory not found: $BACKEND_DIR"

CLI_PYTHON="$(select_python)" || die "python not found; expected backend/.venv/bin/python or a system python"

info "project root: $PROJECT_ROOT"
info "python: $CLI_PYTHON"
info "finviz dir: $DEFAULT_DOWNLOADS_DIR"
info "mc dir: $DEFAULT_DOWNLOADS_DIR"
info "selected w: $W_VALUE"
if [[ -n "$SOURCE_VALUE" ]]; then
  info "selected source: $SOURCE_VALUE"
fi
if [[ -n "$DATE_VALUE" ]]; then
  info "import date override: $DATE_VALUE"
fi

if [[ ${#finviz_list[@]} -gt 0 ]]; then
  import_provider_files "finviz" "${finviz_list[@]}"
else
  import_provider_files "finviz"
fi

if [[ ${#mc_list[@]} -gt 0 ]]; then
  import_provider_files "mc" "${mc_list[@]}"
else
  import_provider_files "mc"
fi

submit_actualiser_jobs

info "done: finviz=$FINVIZ_IMPORTED, mc=$MC_IMPORTED, total=$TOTAL_IMPORTED"
