"use strict";

const state = {
  token: sessionStorage.getItem("grid_token"),
  userId: Number(sessionStorage.getItem("grid_user_id")) || null,
  email: sessionStorage.getItem("grid_email"),
  spritePage: 1,
  packPage: 1,
  selectedSprites: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function element(tag, options = {}) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.type) node.type = options.type;
  if (options.title) node.title = options.title;
  return node;
}

function notify(message, error = false) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.toggle("error", error);
  notice.classList.remove("hidden");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => notice.classList.add("hidden"), 4500);
}

function setSession(token, userId, email) {
  state.token = token;
  state.userId = userId;
  state.email = email;
  if (token) {
    sessionStorage.setItem("grid_token", token);
    sessionStorage.setItem("grid_user_id", String(userId));
    sessionStorage.setItem("grid_email", email);
  } else {
    sessionStorage.removeItem("grid_token");
    sessionStorage.removeItem("grid_user_id");
    sessionStorage.removeItem("grid_email");
  }
  renderSession();
}

function renderSession() {
  $("#session-label").textContent = state.token ? state.email || "已登入" : "未登入";
  $("#logout-button").classList.toggle("hidden", !state.token);
}

async function api(path, options = {}, protectedRequest = false) {
  const headers = new Headers(options.headers || {});
  if (protectedRequest || (state.token && path.startsWith("/packs?"))) {
    if (!state.token) throw new Error("請先登入");
    headers.set("Authorization", `Bearer ${state.token}`);
  }
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {...options, headers});
  if (response.status === 204) return null;
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.arrayBuffer();
  if (!response.ok) {
    const error = data?.error;
    if (response.status === 401 && ["AUTH_TOKEN_INVALID", "AUTH_TOKEN_EXPIRED"].includes(error?.code)) {
      setSession(null, null, null);
    }
    const detailText = Array.isArray(error?.details)
      ? error.details.map((item) => item.message).join("；")
      : "";
    throw new Error(detailText || error?.message || `HTTP ${response.status}`);
  }
  return data;
}

function switchView(viewName) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === viewName));
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === `${viewName}-view`));
  if (viewName === "sprites") loadSprites();
  if (viewName === "packs") loadPacks();
}

function addTags(container, tags) {
  if (!tags) return;
  tags.split(",").forEach((tag) => container.append(element("span", {className: "tag", text: tag})));
}

async function paintSprite(canvas, spriteId) {
  try {
    const bytes = new Uint8ClampedArray(await api(`/sprites/${spriteId}/image`));
    if (bytes.byteLength !== 4096) throw new Error("圖片資料長度錯誤");
    const context = canvas.getContext("2d");
    context.putImageData(new ImageData(bytes, 32, 32), 0, 0);
  } catch (error) {
    canvas.setAttribute("aria-label", error.message);
  }
}

function spriteCard(sprite) {
  const card = element("article", {className: "sprite-card"});
  const preview = element("div", {className: "preview"});
  const canvas = element("canvas");
  canvas.width = 32;
  canvas.height = 32;
  preview.append(canvas);
  paintSprite(canvas, sprite.id);

  const body = element("div", {className: "card-body"});
  const title = element("div", {className: "card-title"});
  title.append(element("h3", {text: sprite.name}), element("span", {className: "meta", text: `#${sprite.id}`}));
  const tags = element("div", {className: "tags"});
  addTags(tags, sprite.tags);
  body.append(title, tags);
  if (sprite.owner_id === state.userId) {
    const actions = element("div", {className: "card-actions"});
    const remove = element("button", {className: "button danger", text: "刪除", type: "button"});
    remove.addEventListener("click", async () => {
      if (!confirm(`確定刪除「${sprite.name}」？素材包內的順序會自動重排。`)) return;
      try {
        await api(`/sprites/${sprite.id}`, {method: "DELETE"}, true);
        notify("素材已刪除");
        loadSprites();
      } catch (error) { notify(error.message, true); }
    });
    actions.append(remove);
    body.append(actions);
  }
  card.append(preview, body);
  return card;
}

function pagination(container, pagination, onPage) {
  container.replaceChildren();
  const previous = element("button", {className: "button ghost", text: "上一頁", type: "button"});
  previous.disabled = !pagination.has_previous;
  previous.addEventListener("click", () => onPage(pagination.page - 1));
  const label = element("span", {text: pagination.total_pages ? `${pagination.page} / ${pagination.total_pages}` : "0 / 0"});
  const next = element("button", {className: "button ghost", text: "下一頁", type: "button"});
  next.disabled = !pagination.has_next;
  next.addEventListener("click", () => onPage(pagination.page + 1));
  container.append(previous, label, next);
}

async function loadSprites() {
  const form = new FormData($("#sprite-filter"));
  const params = new URLSearchParams({
    page: String(state.spritePage),
    page_size: "24",
    tag_mode: form.get("tag_mode"),
    sort: form.get("sort"),
  });
  if (form.get("name").trim()) params.set("name", form.get("name"));
  if (form.get("tags").trim()) params.set("tags", form.get("tags"));
  const grid = $("#sprite-grid");
  grid.replaceChildren(element("div", {className: "empty", text: "載入中…"}));
  try {
    const data = await api(`/sprites?${params}`);
    grid.replaceChildren();
    if (!data.items.length) grid.append(element("div", {className: "empty", text: "沒有符合條件的素材"}));
    data.items.forEach((sprite) => grid.append(spriteCard(sprite)));
    pagination($("#sprite-pagination"), data.pagination, (page) => {
      state.spritePage = page; loadSprites(); window.scrollTo({top: 0, behavior: "smooth"});
    });
  } catch (error) {
    grid.replaceChildren(element("div", {className: "empty", text: error.message}));
  }
}

function packCard(pack) {
  const card = element("article", {className: "pack-card"});
  const info = element("div");
  info.append(
    element("h3", {text: pack.name}),
    element("span", {className: "meta", text: `#${pack.id} · ${pack.sprite_count} 個素材`}),
  );
  const actions = element("div", {className: "card-actions"});
  const view = element("button", {className: "button ghost", text: "查看", type: "button"});
  view.addEventListener("click", () => openPackEditor(pack.id));
  const exportButton = element("button", {className: "button dark", text: "匯出 JSON", type: "button"});
  exportButton.addEventListener("click", () => exportPack(pack.id, pack.name));
  actions.append(view, exportButton);
  if (pack.owner_id === state.userId) {
    const remove = element("button", {className: "button danger", text: "刪除", type: "button"});
    remove.addEventListener("click", async () => {
      if (!confirm(`確定刪除素材包「${pack.name}」？`)) return;
      try {
        await api(`/packs/${pack.id}`, {method: "DELETE"}, true);
        notify("素材包已刪除");
        loadPacks();
      } catch (error) { notify(error.message, true); }
    });
    actions.append(remove);
  }
  card.append(info, actions);
  return card;
}

async function loadPacks() {
  const form = new FormData($("#pack-filter"));
  const mine = form.get("mine") === "on";
  if (mine && !state.token) {
    notify("請先登入後查看自己的素材包", true);
    $("#pack-filter").elements.mine.checked = false;
  }
  const params = new URLSearchParams({
    page: String(state.packPage),
    page_size: "20",
    mine: String(mine && Boolean(state.token)),
    sort: form.get("sort"),
  });
  if (form.get("name").trim()) params.set("name", form.get("name"));
  const grid = $("#pack-grid");
  grid.replaceChildren(element("div", {className: "empty", text: "載入中…"}));
  try {
    const data = await api(`/packs?${params}`);
    grid.replaceChildren();
    if (!data.items.length) grid.append(element("div", {className: "empty", text: "沒有符合條件的素材包"}));
    data.items.forEach((pack) => grid.append(packCard(pack)));
    pagination($("#pack-pagination"), data.pagination, (page) => { state.packPage = page; loadPacks(); });
  } catch (error) {
    grid.replaceChildren(element("div", {className: "empty", text: error.message}));
  }
}

async function exportPack(id, name) {
  try {
    const data = await api(`/packs/${id}/export`);
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json;charset=utf-8"});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${name.replace(/[\\/:*?"<>|]/g, "_") || `pack-${id}`}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) { notify(error.message, true); }
}

function renderSelectedSprites(editable) {
  const list = $("#selected-sprites");
  list.replaceChildren();
  $("#selected-count").textContent = `${state.selectedSprites.length} 個`;
  state.selectedSprites.forEach((sprite, index) => {
    const item = element("li", {className: "selected-item"});
    item.draggable = editable;
    item.dataset.index = String(index);
    item.append(element("span", {className: "item-name", text: `${index}. ${sprite.name}`}));
    if (editable) {
      const actions = element("div", {className: "mini-actions"});
      const up = element("button", {text: "↑", type: "button", title: "上移"});
      const down = element("button", {text: "↓", type: "button", title: "下移"});
      const remove = element("button", {text: "×", type: "button", title: "移除"});
      up.disabled = index === 0;
      down.disabled = index === state.selectedSprites.length - 1;
      up.addEventListener("click", () => moveSelected(index, index - 1));
      down.addEventListener("click", () => moveSelected(index, index + 1));
      remove.addEventListener("click", () => { state.selectedSprites.splice(index, 1); renderSelectedSprites(true); renderLibrary(); });
      actions.append(up, down, remove);
      item.append(actions);
      item.addEventListener("dragstart", () => item.classList.add("dragging"));
      item.addEventListener("dragend", () => item.classList.remove("dragging"));
      item.addEventListener("dragover", (event) => event.preventDefault());
      item.addEventListener("drop", (event) => {
        event.preventDefault();
        const source = Number(list.querySelector(".dragging")?.dataset.index);
        if (Number.isInteger(source)) moveSelected(source, index);
      });
    }
    list.append(item);
  });
}

function moveSelected(from, to) {
  if (to < 0 || to >= state.selectedSprites.length || from === to) return;
  const [item] = state.selectedSprites.splice(from, 1);
  state.selectedSprites.splice(to, 0, item);
  renderSelectedSprites(true);
}

let editorLibrary = [];
function renderLibrary() {
  const container = $("#editor-library");
  container.replaceChildren();
  const selectedIds = new Set(state.selectedSprites.map((sprite) => sprite.id));
  editorLibrary.forEach((sprite) => {
    const row = element("div", {className: "library-item"});
    row.append(element("span", {className: "item-name", text: sprite.name}));
    const add = element("button", {className: "button ghost", text: selectedIds.has(sprite.id) ? "已加入" : "加入", type: "button"});
    add.disabled = selectedIds.has(sprite.id);
    add.addEventListener("click", () => {
      state.selectedSprites.push(sprite);
      renderSelectedSprites(true);
      renderLibrary();
    });
    row.append(add);
    container.append(row);
  });
  if (!editorLibrary.length) container.append(element("div", {className: "empty", text: "沒有符合的素材"}));
}

async function loadEditorLibrary() {
  const params = new URLSearchParams({page: "1", page_size: "100", sort: "name_asc"});
  const search = $("#editor-search").value.trim();
  if (search) params.set("name", search);
  try {
    const data = await api(`/sprites?${params}`);
    editorLibrary = data.items;
    renderLibrary();
  } catch (error) { notify(error.message, true); }
}

async function openPackEditor(packId = null) {
  if (!state.token && packId === null) {
    notify("請先登入後建立素材包", true);
    switchView("account");
    return;
  }
  $("#pack-id").value = packId || "";
  state.selectedSprites = [];
  let editable = true;
  if (packId !== null) {
    try {
      const pack = await api(`/packs/${packId}`);
      $("#pack-name").value = pack.name;
      state.selectedSprites = pack.sprites.map((sprite) => ({id: sprite.id, name: sprite.name, tags: sprite.tags}));
      editable = pack.owner_id === state.userId;
      $("#pack-dialog-title").textContent = editable ? "編輯素材包" : "查看素材包";
    } catch (error) { notify(error.message, true); return; }
  } else {
    $("#pack-name").value = "";
    $("#pack-dialog-title").textContent = "建立素材包";
  }
  $("#pack-name").disabled = !editable;
  $("#pack-form").querySelector('button[type="submit"]').classList.toggle("hidden", !editable);
  $(".editor-columns section:last-child").classList.toggle("hidden", !editable);
  renderSelectedSprites(editable);
  if (editable) await loadEditorLibrary();
  $("#pack-dialog").showModal();
}

$$(".tab").forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));
$$(".close-dialog").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));

$("#sprite-filter").addEventListener("submit", (event) => { event.preventDefault(); state.spritePage = 1; loadSprites(); });
$("#pack-filter").addEventListener("submit", (event) => { event.preventDefault(); state.packPage = 1; loadPacks(); });
$("#open-upload").addEventListener("click", () => {
  if (!state.token) { notify("請先登入後上傳素材", true); switchView("account"); return; }
  $("#upload-dialog").showModal();
});
$("#create-pack").addEventListener("click", () => openPackEditor());
$("#editor-search-button").addEventListener("click", loadEditorLibrary);
$("#editor-search").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); loadEditorLibrary(); } });

$("#register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  try {
    await api("/auth/register", {method: "POST", body: JSON.stringify({email: form.get("email"), password: form.get("password")})});
    formElement.reset();
    notify("註冊成功，請使用新帳號登入");
  } catch (error) { notify(error.message, true); }
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  try {
    const credentials = {email: form.get("email"), password: form.get("password")};
    const data = await api("/auth/login", {method: "POST", body: JSON.stringify(credentials)});
    const segment = data.access_token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(segment.padEnd(Math.ceil(segment.length / 4) * 4, "=")));
    setSession(data.access_token, Number(payload.sub), credentials.email.trim().toLowerCase());
    formElement.reset();
    notify("登入成功");
    switchView("sprites");
  } catch (error) { notify(error.message, true); }
});

$("#logout-button").addEventListener("click", async () => {
  try { await api("/auth/logout", {method: "POST"}, true); }
  catch (error) { notify(error.message, true); }
  finally { setSession(null, null, null); }
});

$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  try {
    await api("/sprites", {method: "POST", body: form}, true);
    formElement.reset();
    $("#upload-dialog").close();
    notify("素材已上傳");
    state.spritePage = 1;
    loadSprites();
  } catch (error) { notify(error.message, true); }
});

$("#pack-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("#pack-id").value;
  const body = {name: $("#pack-name").value, sprite_ids: state.selectedSprites.map((sprite) => sprite.id)};
  try {
    await api(id ? `/packs/${id}` : "/packs", {method: id ? "PATCH" : "POST", body: JSON.stringify(body)}, true);
    $("#pack-dialog").close();
    notify(id ? "素材包已更新" : "素材包已建立");
    state.packPage = 1;
    loadPacks();
  } catch (error) { notify(error.message, true); }
});

renderSession();
loadSprites();
