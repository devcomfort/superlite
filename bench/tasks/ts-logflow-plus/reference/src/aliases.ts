export const SERVICE_ALIASES: Record<string, string> = {
  authsvc: "auth",
  "auth-service": "auth",
  "api-gw": "api",
  gateway: "api",
  database: "db",
  postgres: "db",
  pg: "db",
  cache: "redis",
};

/** Lower-cased service name with aliases resolved. */
export function canonicalService(name: string): string {
  const key = name.toLowerCase();
  return Object.hasOwn(SERVICE_ALIASES, key) ? SERVICE_ALIASES[key] : key;
}

/** Lower-cased field key with every '.' replaced by '_'. */
export function normaliseKey(key: string): string {
  return key.toLowerCase().replace(/\./g, "_");
}
