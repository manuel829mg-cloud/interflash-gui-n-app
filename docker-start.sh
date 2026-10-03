#!/bin/sh
set -eu

cd /app

mkdir -p storage/app/public storage/framework/cache storage/framework/sessions storage/framework/views storage/logs bootstrap/cache
chmod -R 775 storage bootstrap/cache || true

php artisan config:clear || true
php artisan cache:clear || true

attempt=1
until php artisan migrate --force; do
  if [ "$attempt" -ge 30 ]; then
    echo "Database migration failed after $attempt attempts."
    exit 1
  fi
  echo "Waiting for database... attempt $attempt/30"
  attempt=$((attempt + 1))
  sleep 3
done

if [ -n "${ADMIN_EMAIL:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
  if php artisan tinker --execute='exit(\App\Models\User::where("email", env("ADMIN_EMAIL"))->exists() ? 0 : 1);' >/dev/null 2>&1; then
    echo "INTER Flash administrator already exists; skipping initial seed."
  else
    php artisan db:seed --force
  fi
fi

php artisan storage:link || true
php artisan optimize:clear || true

exec php artisan serve --host=0.0.0.0 --port="${PORT:-8080}"
