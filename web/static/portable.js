// Tagged JSON preserves review types; file bytes are carried as separate artifacts.
export function encodePortable(value) {
  if (value instanceof Set)
    return { $type: "Set", values: [...value].map(encodePortable) };
  if (value instanceof Map)
    return {
      $type: "Map",
      values: [...value].map(([k, v]) => [
        encodePortable(k),
        encodePortable(v),
      ]),
    };
  if (value instanceof Date)
    return { $type: "Date", value: value.toISOString() };
  if (value instanceof Uint8Array)
    return { $type: "Uint8Array", values: [...value] };
  if (Array.isArray(value)) return value.map(encodePortable);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, encodePortable(v)]),
    );
  return value;
}
export function decodePortable(value) {
  if (value?.$type === "Set") return new Set(value.values.map(decodePortable));
  if (value?.$type === "Map")
    return new Map(
      value.values.map(([k, v]) => [decodePortable(k), decodePortable(v)]),
    );
  if (value?.$type === "Date") return new Date(value.value);
  if (value?.$type === "Uint8Array") return new Uint8Array(value.values);
  if (Array.isArray(value)) return value.map(decodePortable);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, decodePortable(v)]),
    );
  return value;
}
