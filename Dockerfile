FROM php:8.3-cli-bookworm

ARG SOURCE_COMMIT=56c6e7347bf9291b7408a316d8302c021a05b27f
ENV COMPOSER_ALLOW_SUPERUSER=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git unzip patch curl ca-certificates nodejs npm python3 \
    libzip-dev libpng-dev libjpeg62-turbo-dev libfreetype6-dev \
    libicu-dev libonig-dev libxml2-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j$(nproc) pdo_mysql bcmath intl zip gd mbstring pcntl opcache exif sockets \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer

WORKDIR /app
RUN git clone https://github.com/CodePagol/ISP-Mikrotik-Billing.git . \
    && git checkout "$SOURCE_COMMIT"

COPY interflash-patch-*.part /tmp/interflash-patches/
RUN cat /tmp/interflash-patches/interflash-patch-*.part > /tmp/interflash.patch \
    && patch -p2 < /tmp/interflash.patch \
    && rm -rf /tmp/interflash-patches /tmp/interflash.patch

RUN python3 - <<'PY'
from pathlib import Path

p = Path('database/seeders/SuperAdminSeeder.php')
s = p.read_text()
s = s.replace(
    "$password = (string) env('ADMIN_PASSWORD', '');\n\n        if ($email === '' || $password === '') {\n            $this->command?->warn('ADMIN_EMAIL / ADMIN_PASSWORD are empty. Super Admin was not created.');\n            return;\n        }",
    "$password = (string) env('ADMIN_PASSWORD', '');\n        if ($password === '') {\n            $password = substr(hash('sha256', (string) config('app.key')), 0, 20);\n        }\n\n        if ($email === '') {\n            $this->command?->warn('ADMIN_EMAIL is empty. Super Admin was not created.');\n            return;\n        }"
)
p.write_text(s)

# The single-domain route switch is referenced from inside the main-domain closure.
r = Path('routes/web.php')
rs = r.read_text()
rs = rs.replace(
    "Route::domain($baseDomain)->group(function () {",
    "Route::domain($baseDomain)->group(function () use ($singleDomain) {",
    1,
)
r.write_text(rs)

# Railway terminates HTTPS at its proxy. Trust forwarded headers so Laravel
# generates HTTPS URLs for Vite CSS/JS and Livewire instead of mixed-content HTTP.
b = Path('bootstrap/app.php')
bs = b.read_text()
needle = "    ->withMiddleware(function (Middleware $middleware) {\n"
replacement = needle + "        $middleware->trustProxies(at: '*');\n"
if "$middleware->trustProxies(at: '*');" not in bs:
    bs = bs.replace(needle, replacement, 1)
b.write_text(bs)
PY

# Upstream imports livewire-sortable but omits it from package.json.
# Install that missing runtime dependency before building the Vite manifest.
RUN cp .env.example .env \
    && npm ci \
    && npm install --no-save livewire-sortable@1.0.0 \
    && npm run build \
    && composer install --no-dev --prefer-dist --no-interaction --optimize-autoloader \
    && mkdir -p storage/app/public storage/framework/cache storage/framework/sessions storage/framework/views storage/logs bootstrap/cache \
    && chmod -R 775 storage bootstrap/cache

COPY docker-start.sh /usr/local/bin/docker-start
RUN chmod +x /usr/local/bin/docker-start

EXPOSE 8080
CMD ["docker-start"]
