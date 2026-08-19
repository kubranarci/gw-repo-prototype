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
