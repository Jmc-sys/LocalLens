import { useEffect, useState } from "react";
import { api } from "./api";

export default function PopularPhotoTags({ onSearch }) {
  const [tags, setTags] = useState([]);
  useEffect(() => {
    let active = true;
    api("/ai/tags").then(items => {
      if (active) setTags((Array.isArray(items) ? items : items?.tags || []).slice(0, 8));
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  if (!tags.length) return null;
  return <div className="ll-v615-popular-tags" aria-label="Suggested photo searches">
    <span>Try a tag</span>
    {tags.map(item => <button type="button" key={item.tag} onClick={() => onSearch?.(item.tag)}>
      {item.tag.replace(/[-_]/g, " ")}
    </button>)}
  </div>;
}
