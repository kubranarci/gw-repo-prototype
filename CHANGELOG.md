# Changelog

For detailed technical documentation, see [doc/TECHNICAL_DOCS.md](doc/TECHNICAL_DOCS.md).

## [2026-08-20] - Work Directory Integration & Enhanced Trace Support

### Added

#### Work Directory Scanning
- **Privacy-safe disk usage tracking** - Extracts only numerical metrics (MB, bytes), NEVER stores file paths, filenames, or sample names
- **Targeted scanning** - Only scans tasks from execution trace (not all work directories)
- **New metrics**: `disk_usage_mb`, `read_bytes`, `write_bytes`, `peak_vmem_mb`, `peak_rss_mb`
- **Graceful handling** - Missing work directories are skipped silently (no failures)

#### Files Created
| File | Purpose |
|------|---------|
| `client/work_scanner.py` | Privacy-safe work directory scanner |
| `test_work_scanner.py` | Integration tests (5 tests, 100% pass rate) |

#### Enhanced Trace Support
- **Dual format support** - Handles both old and new Nextflow execution trace formats
- **New format fields**: `module`, `container`, `cpus`, `time`, `memory`, `%mem`
- **Old format fallback** - Gracefully handles traces without these fields

### Changed

#### Database Schema
- **ProcessExecution model** - Added 5 new fields for work directory metrics
- All fields are optional (backward compatible with existing data)

#### Client
- **New parameter** - `--work-dir` for work directory scanning
- **Enhanced parsing** - Automatically detects and parses both trace formats
- **Better feedback** - Shows scan progress and success rate

### Performance

- **Scan speed**: ~2 seconds for 105 tasks
- **Success rate**: 100% (all tasks found in test)
- **Privacy**: Zero file paths or filenames stored

### Example Usage

```bash
# Submit with work directory scanning
python client/client.py ./results/pipeline_info \
    --work-dir ./results/work \
    --api-key ${API_KEY}
```

### Test Results

```
✓ PASS: Single Task Scan
✓ PASS: Targeted Scanning  
✓ PASS: Privacy Compliance
✓ PASS: Missing Task Handling
✓ PASS: Readable Units

Total: 5/5 tests passed (100.0%)
```

---

# Consolidated Configuration Implementation

## What Changed

### Before
- Multiple `.env` files scattered across directories (`api/.env`, `client/.env`, `db/.env`)
- Manual API key generation
- Difficult to manage and synchronize

### After
- **Single `.env` file** at project root
- **Auto-generated API key** on first setup
- **Symlinks** for backward compatibility
- **Simple setup script**

## Files Created

| File | Purpose |
|------|---------|
| `.env` | Single source of truth for all configuration |
| `setup.py` | Python script to generate API key and config |
| `setup.sh` | Shell wrapper for setup process |
| `QUICKSTART.md` | User guide for new users |

## Files Modified

| File | Change |
|------|--------|
| `docker-compose.yml` | Now references root `.env` instead of subdirectory files |
| `api/migrate.py` | Added auto-generation of API key and .env file |

## Files Removed

| File | Replacement |
|------|-------------|
| `api/.env` | Symlink → `../.env` |
| `client/.env` | Symlink → `../.env` |
| `db/.env` | Symlink → `../.env` |

## Usage

### First Time Setup

```bash
./setup.sh
```

This generates:
- Unique API key (using `secrets.token_urlsafe(32)`)
- Database credentials
- Default institute ID

### View Current Configuration

```bash
cat .env
```

### Regenerate API Key

```bash
rm .env
./setup.sh
```

## Benefits

1. **Single Source of Truth**: One file to manage all configuration
2. **No Manual Steps**: API key auto-generated
3. **Easy to Reset**: Delete and regenerate
4. **Backward Compatible**: Symlinks maintain existing paths
5. **Documented**: Clear instructions in QUICKSTART.md

## Security Notes

- API key is generated using Python's `secrets` module (cryptographically secure)
- Key is 32 bytes URL-safe base64-encoded
- Stored only in `.env` file (not committed to git)
- Can be regenerated anytime

## Migration from Old Setup

If you have existing `.env` files:

```bash
# Backup old configs
cp api/.env api/.env.backup
cp client/.env client/.env.backup

# Remove old files
rm api/.env client/.env db/.env

# Run new setup
./setup.sh

# Verify symlinks
ls -la */.env
```

Your old API key will be replaced with a new one. If you want to keep the old key:

```bash
# Extract old API key
OLD_KEY=$(grep API_KEY api/.env.backup | cut -d'=' -f2)

# Edit .env and replace the generated key
sed -i "" "s/^API_KEY=.*/API_KEY=$OLD_KEY/" .env
```
