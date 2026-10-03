FROM php:8.3-cli-bookworm

ARG SOURCE_COMMIT=56c6e7347bf9291b7408a316d8302c021a05b27f

RUN apt-get update && apt-get install -y --no-install-recommends \
    git unzip patch curl ca-certificates nodejs npm \
    libzip-dev libpng-dev libjpeg62-turbo-dev libfreetype6-dev \
    libicu-dev libonig-dev libxml2-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j$(nproc) pdo_mysql bcmath intl zip gd mbstring pcntl opcache exif \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer

WORKDIR /app
RUN git clone https://github.com/CodePagol/ISP-Mikrotik-Billing.git . \
    && git checkout "$SOURCE_COMMIT"

COPY interflash-patch-*.part /tmp/interflash-patches/
RUN cat /tmp/interflash-patches/interflash-patch-*.part > /tmp/interflash.patch \
    && patch -p2 < /tmp/interflash.patch \
    && rm -rf /tmp/interflash-patches /tmp/interflash.patch

RUN cp .env.example .env \
    && composer install --no-dev --prefer-dist --no-interaction --optimize-autoloader \
    && npm ci \
    && npm run build \
    && mkdir -p storage/app/public storage/framework/cache storage/framework/sessions storage/framework/views storage/logs bootstrap/cache \
    && chmod -R 775 storage bootstrap/cache

COPY docker-start.sh /usr/local/bin/docker-start
RUN chmod +x /usr/local/bin/docker-start

EXPOSE 8080
CMD ["docker-start"]
