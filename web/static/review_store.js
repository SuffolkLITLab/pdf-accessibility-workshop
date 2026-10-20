// Local-only review storage. Records contain document bytes and review decisions.
const database = new Promise((resolve, reject) => {
  const request = indexedDB.open("pdf-accessibility-workshop", 1);
  request.onupgradeneeded = () => request.result.createObjectStore("reviews", { keyPath: "id" });
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});
async function operation(mode, action) {
  const db = await database;
  return new Promise((resolve, reject) => {
    const tx = db.transaction("reviews", mode);
    const request = action(tx.objectStore("reviews"));
    tx.oncomplete = () => resolve(request.result);
    tx.onabort = tx.onerror = () => reject(tx.error || request.error);
  });
}
export const saveReview = (record) => operation("readwrite", store => store.put(record));
export const loadReview = (id) => operation("readonly", store => store.get(id));
export const deleteReview = (id) => operation("readwrite", store => store.delete(id));
export const listReviews = () => operation("readonly", store => store.getAll());
