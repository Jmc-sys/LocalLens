// Size is a necessary condition for byte-identical media. One batched lookup
// lets new photos skip client-side hashing; all potential matches are SHA-256
// verified before transfer, even if the original filename has changed.
export function photoCandidateKey(file) {
  return Number(file.size);
}

export async function possiblePhotoDuplicates(images, api) {
  const candidateSizes = new Set();
  const uniqueSizes = [...new Set(images.map(file => file.size))];
  for (let offset = 0; offset < uniqueSizes.length; offset += 300) {
    const chunk = uniqueSizes.slice(offset, offset + 300);
    const response = await api('/media/check-photo-sizes', {
      method: 'POST',
      body: JSON.stringify({ sizes: chunk }),
    });
    for (const size of response.sizes || []) candidateSizes.add(Number(size));
  }
  return candidateSizes;
}
