import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// Anonymous client id
export function getClientId() {
  let id = localStorage.getItem("manga_client_id");
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem("manga_client_id", id);
  }
  return id;
}

export const api = axios.create({ baseURL: API });

// Convert backend relative /api/files/... to absolute URL
export function fileUrl(url) {
  if (!url) return null;
  if (url.startsWith("http")) return url;
  return `${BACKEND_URL}${url}`;
}
