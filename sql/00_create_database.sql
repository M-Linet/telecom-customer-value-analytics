-- 00_create_database.sql  (run against the default "postgres" database)
DROP DATABASE IF EXISTS telecom_cva;
CREATE DATABASE telecom_cva WITH ENCODING = 'UTF8' TEMPLATE = template0;
