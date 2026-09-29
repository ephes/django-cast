(function () {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return;
  }

  // Morph a post's title and first overview image between a post list and the
  // post's detail page during cross-document "cast-page" view transitions.
  // Names are assigned only to the one post involved, so pages never carry
  // colliding names and htmx pagination swaps are unaffected.
  var TRANSITION_TYPE = "cast-page";
  var STORAGE_KEY = "cast-post-view-transition";
  var TITLE_NAME = "cast-post-title";
  var IMAGE_NAME = "cast-post-image";

  function pagePath(url) {
    try {
      var parsed = new URL(url, document.baseURI);
      return parsed.origin + parsed.pathname;
    } catch (error) {
      return null;
    }
  }

  function findArticle(url) {
    var path = pagePath(url);
    if (!path) {
      return null;
    }
    var links = document.querySelectorAll("article > header a[href]");
    for (var i = 0; i < links.length; i++) {
      if (pagePath(links[i].href) === path) {
        return links[i].closest("article");
      }
    }
    return null;
  }

  function isCastPageTransition(viewTransition) {
    return Boolean(viewTransition && viewTransition.types && viewTransition.types.has(TRANSITION_TYPE));
  }

  function nameElements(article, viewTransition) {
    var named = [];
    var title = article.querySelector("header h1, header h2, header h3");
    var image = article.querySelector(".block-overview img");
    if (title) {
      title.style.viewTransitionName = TITLE_NAME;
      named.push(title);
    }
    if (image) {
      image.style.viewTransitionName = IMAGE_NAME;
      named.push(image);
    }
    // Clear the names once the transition ends, so a page restored from the
    // back/forward cache or a later htmx swap does not reuse them.
    viewTransition.finished.finally(function () {
      named.forEach(function (element) {
        element.style.viewTransitionName = "";
      });
    });
  }

  function readHandoff(consume) {
    try {
      var value = window.sessionStorage.getItem(STORAGE_KEY);
      if (consume) {
        window.sessionStorage.removeItem(STORAGE_KEY);
      }
      return value ? JSON.parse(value) : null;
    } catch (error) {
      return null;
    }
  }

  function isHandoffForThisPage(handoff) {
    return Boolean(handoff && handoff.to === pagePath(window.location.href));
  }

  function writeHandoff(handoff) {
    try {
      if (handoff) {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(handoff));
      } else {
        window.sessionStorage.removeItem(STORAGE_KEY);
      }
    } catch (error) {
      // Storage may be unavailable; the page then loads without the morph.
    }
  }

  window.addEventListener("pageswap", function (event) {
    var viewTransition = event.viewTransition;
    var entry = event.activation && event.activation.entry;
    if (!isCastPageTransition(viewTransition) || !entry || !entry.url) {
      writeHandoff(null);
      return;
    }
    // Leaving a list for a post, or leaving a post's own detail page.
    var postUrl = findArticle(entry.url) ? entry.url : findArticle(window.location.href) ? window.location.href : null;
    if (!postUrl) {
      writeHandoff(null);
      return;
    }
    nameElements(findArticle(postUrl), viewTransition);
    writeHandoff({ post: pagePath(postUrl), to: pagePath(entry.url) });
  });

  // This script runs in the <head>. When a handoff targets this page, hold the
  // first render until the document is parsed, so that pagereveal can find the
  // incoming post. The expect link points at an id that no page defines, which
  // keeps rendering blocked until parsing completes. Other page loads are not
  // blocked.
  if (isHandoffForThisPage(readHandoff(false)) && document.head) {
    var expectLink = document.createElement("link");
    expectLink.rel = "expect";
    expectLink.href = "#cast-post-view-transition-parsed";
    expectLink.setAttribute("blocking", "render");
    document.head.appendChild(expectLink);
  }

  window.addEventListener("pagereveal", function (event) {
    var handoff = readHandoff(true);
    var viewTransition = event.viewTransition;
    if (!isHandoffForThisPage(handoff) || !isCastPageTransition(viewTransition)) {
      return;
    }
    var article = findArticle(handoff.post);
    if (article) {
      nameElements(article, viewTransition);
    }
  });
})();
