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

if [ -n "${ADMIN_EMAIL:-}" ]; then
  if php artisan tinker --execute='exit(\App\Models\User::where("email", env("ADMIN_EMAIL"))->exists() ? 0 : 1);' >/dev/null 2>&1; then
    echo "INTER Flash administrator already exists; skipping initial seed."
  else
    php artisan db:seed --force
  fi
fi

# Keep the configured INTER Flash administrator password usable after the
# first seed as well. The User model hashes the assigned password automatically.
if [ -n "${ADMIN_EMAIL:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
  php artisan tinker --execute='$u=\App\Models\User::where("email", env("ADMIN_EMAIL"))->first(); if ($u) { $u->password = env("ADMIN_PASSWORD"); $u->save(); }' >/dev/null 2>&1 \
    && echo "INTER Flash administrator credentials synchronized." \
    || echo "Warning: administrator credentials could not be synchronized."
fi

php artisan storage:link || true
php artisan optimize:clear || true

# Start Laravel and perform one local request with the real Railway Host header
# so domain-scoped routes are tested and any exception lands in Railway logs.
php artisan serve --host=0.0.0.0 --port="${PORT:-8080}" --no-reload &
server_pid=$!
sleep 2
host="${RAILWAY_PUBLIC_DOMAIN:-interflash-laravel-test-production.up.railway.app}"
status="$(curl -sS -H "Host: $host" -o /tmp/interflash-root.html -w '%{http_code}' "http://127.0.0.1:${PORT:-8080}/" || true)"
echo "INTER Flash root self-test for $host HTTP status: ${status:-request-failed}"
wait "$server_pid"
