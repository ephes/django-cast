(function () {
  const config = JSON.parse(document.getElementById("twitter-player-config").textContent);
  podlovePlayer("[data-twitter-player]", config, {
    version: 5,
    theme: {
      tokens: {
        brandLightest: "#3c6f97",
        contrast: "#fff",
        brandDark: "#fff",
        brand: "#fff",
      },
    },
  });
})();
