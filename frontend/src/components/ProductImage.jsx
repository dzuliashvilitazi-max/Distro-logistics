const FALLBACK_IMAGE = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 240"><rect width="320" height="240" fill="#edf3ee"/><circle cx="258" cy="50" r="44" fill="#d5e7d8"/><path d="M91 77h138l-12 126H103L91 77Z" fill="#fff" stroke="#52785b" stroke-width="6"/><path d="M91 77h138l-8 39H99L91 77Z" fill="#8eb59a"/><path d="M138 147h44" stroke="#52785b" stroke-width="7" stroke-linecap="round"/><path d="M160 138c-16-16-31-5-26 8 4 11 20 17 26 19 6-2 22-8 26-19 5-13-10-24-26-8Z" fill="#c1d9c5"/><text x="160" y="225" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#52785b">PRODUCT IMAGE</text></svg>'
)}`;

export default function ProductImage({ image, alt = "", className = "", ...props }) {
  return (
    <img
      {...props}
      src={image || FALLBACK_IMAGE}
      alt={alt}
      className={className}
      onError={(event) => {
        event.currentTarget.onerror = null;
        event.currentTarget.src = FALLBACK_IMAGE;
      }}
    />
  );
}
