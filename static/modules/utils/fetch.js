/**
 * MessagePack fetch utilities
 * All API calls should use these instead of raw fetch()
 *
 * MessagePack library loaded via CDN, available as window.MessagePack
 */

// Get MessagePack from global scope (loaded via CDN)
const msgpack = window.MessagePack || {};

/**
 * Fetch data from API endpoint with MessagePack decoding.
 * @param {string} url - API endpoint
 * @param {object} options - fetch options (optional)
 * @returns {Promise<any>} Decoded response data
 */
export async function fetchMsgpack(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Accept': 'application/msgpack',
      ...options.headers,
    }
  });

  if (!response.ok) {
    let errorMsg = 'Request failed';
    try {
      const buffer = await response.arrayBuffer();
      const decoded = msgpack.decode(new Uint8Array(buffer));
      errorMsg = decoded.error || errorMsg;
    } catch (e) {
      errorMsg = response.statusText;
    }
    throw new Error(errorMsg);
  }

  const buffer = await response.arrayBuffer();
  return msgpack.decode(new Uint8Array(buffer));
}

/**
 * POST data to API endpoint with MessagePack encoding/decoding.
 * @param {string} url - API endpoint
 * @param {object} data - Data to send
 * @returns {Promise<any>} Decoded response data
 */
export async function postMsgpack(url, data) {
  return fetchMsgpack(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/msgpack',
    },
    body: msgpack.encode(data)
  });
}

/**
 * GET request with query params and MessagePack response.
 * @param {string} url - Base URL
 * @param {object} params - Query parameters
 * @returns {Promise<any>} Decoded response data
 */
export async function getMsgpack(url, params = {}) {
  const queryString = new URLSearchParams(params).toString();
  const fullUrl = queryString ? `${url}?${queryString}` : url;
  return fetchMsgpack(fullUrl);
}
