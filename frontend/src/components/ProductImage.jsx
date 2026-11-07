const FALLBACK_IMAGE = `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 240"><rect width="320" height="240" fill="#edf3ee"/><circle cx="258" cy="50" r="44" fill="#d5e7d8"/><path d="M91 77h138l-12 126H103L91 77Z" fill="#fff" stroke="#52785b" stroke-width="6"/><path d="M91 77h138l-8 39H99L91 77Z" fill="#8eb59a"/><path d="M138 147h44" stroke="#52785b" stroke-width="7" stroke-linecap="round"/><path d="M160 138c-16-16-31-5-26 8 4 11 20 17 26 19 6-2 22-8 26-19 5-13-10-24-26-8Z" fill="#c1d9c5"/><text x="160" y="225" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#52785b">PRODUCT IMAGE</text></svg>'
)}`;

const KEYWORDS = [
  [["snickers", "სნიკერს", "chocolate", "შოკოლად", "candy", "კანფეტ"], "chocolate"],
  [["pelmeni", "dumpling", "пельмен", "პილმენ", "ხინკალ"], "dumplings"],
  [["coca-cola", "coca cola", "coke", "კოკა-კოლა", "კოკაკოლა", "კოლა"], "cola"],
  [["orange juice", "juice", "წვენი", "წვენ"], "juice"],
  [["milk", "yogurt", "cheese", "რძე", "იოგურტ", "ყველი"], "dairy"],
  [["bread", "bakery", "პური", "პურეულ"], "bread"],
  [["meat", "chicken", "beef", "ხორცი", "ქათამ"], "meat"],
  [["fruit", "apple", "banana", "ხილი", "ვაშლი", "ბანანი"], "fruit"],
  [["vegetable", "tomato", "potato", "ბოსტნეულ", "პომიდორ", "კარტოფილ"], "vegetables"],
  [["coffee", "ყავა"], "coffee"],
  [["tea", "ჩაი"], "tea"],
  [["pasta", "macaroni", "მაკარონ", "პასტა"], "pasta"],
  [["rice", "ბრინჯ"], "rice"],
  [["water", "წყალი"], "water"],
  [["snack", "chips", "სნექ", "ჩიფს"], "snacks"],
  [["drink", "beverage", "სასმელ"], "soft-drink"],
];

function keywordFallback(name, category) {
  const productName = `${name || ""}`.toLowerCase();
  const categoryName = `${category || ""}`.toLowerCase();
  const keyword = KEYWORDS.find(([terms]) => terms.some((term) => productName.includes(term)))?.[1]
    || KEYWORDS.find(([terms]) => terms.some((term) => categoryName.includes(term)))?.[1]
    || productName.match(/[a-z]+/)?.[0]
    || "groceries";
  const seed = Array.from(`${productName}|${categoryName}`).reduce(
    (hash, character) => Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0,
    2166136261,
  );
  return `https://loremflickr.com/800/600/${encodeURIComponent(keyword)}?lock=${seed}`;
}

export default function ProductImage({ image, name, category, alt = "", className = "", ...props }) {
  const themedFallback = keywordFallback(name, category);
  return (
    <img
      {...props}
      src={image || themedFallback}
      alt={alt}
      className={className}
      onError={(event) => {
        if (event.currentTarget.src !== themedFallback) {
          event.currentTarget.src = themedFallback;
          return;
        }
        event.currentTarget.onerror = null;
        event.currentTarget.src = FALLBACK_IMAGE;
      }}
    />
  );
}
