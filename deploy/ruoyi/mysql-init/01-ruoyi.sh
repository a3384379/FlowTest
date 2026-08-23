#!/bin/sh

mysql \
  --protocol=socket \
  --default-character-set=utf8mb4 \
  -uroot \
  -p"$MYSQL_ROOT_PASSWORD" \
  --database="$MYSQL_DATABASE" \
  < /opt/ruoyi/seed/ry.sql
