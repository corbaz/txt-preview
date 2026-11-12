// TXT Preview frontend shell.
const pywebview = window.pywebview;

function setTab(name) {
  document.querySelectorAll(".seg").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.dataset.page === name));
}

document.getElementById("segmented").addEventListener("click", (e) => {
  const btn = e.target.closest(".seg");
  if (btn) setTab(btn.dataset.tab);
});

window.addEventListener("pywebviewready", async () => {
  const badge = document.getElementById("version-badge");
  badge.textContent = "v" + (await window.pywebview.api.app_version());
});
