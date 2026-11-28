import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve, sep } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_CORE || "playwright-core");
const frontend = fileURLToPath(new URL("../", import.meta.url));
const origin = "http://gilit.test";
const routes = JSON.parse(await readFile(new URL("../js/mock/routes.json", import.meta.url)));
const date = new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10);
const from = { name: "김해시청", address: "경남 김해시", lat: 35.2285, lng: 128.8894 };
const to = { name: "동의대학교", address: "부산 부산진구", lat: 35.1441, lng: 129.0336 };
const internal = "TEST_ONLY_AUTH_TOKEN_AND_INTERNAL_STACK";
let browser;

before(async () => {
  browser = await chromium.launch({
    executablePath: process.env.CHROME_BIN || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
});

after(async () => browser?.close());

function scenario(name, run, respond = route => route.fulfill({ json: routes })) {
  test(name, { timeout: 20_000 }, async () => {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    page.setDefaultTimeout(4_000);
    const requests = [];
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      switch (url.pathname) {
        case "/api/routes":
          requests.push(url.search);
          return respond(route, requests.length);
        case "/api/places":
          return route.fulfill({ json: [from, to].filter(place => place.name.includes(url.searchParams.get("q"))) });
        case "/api/config":
          return route.fulfill({ json: {} });
        case "/api/auth/me":
          return route.fulfill({ status: 401, json: {} });
      }
      if (url.pathname.startsWith("/api/")) return route.fulfill({ status: 404, json: {} });
      const path = resolve(frontend, "." + url.pathname);
      if (!path.startsWith(resolve(frontend) + sep)) return route.abort();
      return route.fulfill({ path }).catch(() => route.fulfill({ status: 404 }));
    });
    try {
      await page.goto(origin + "/index.html");
      await page.locator(".nav-menu").getByRole("link", { name: "길찾기" }).click();
      await page.waitForURL("**/pages/search.html");
      await page.locator('#search-submit').filter({ hasText: "출발시각 찾기" }).waitFor();
      await run(page, requests);
    } finally {
      await page.close();
    }
  });
}

const field = (page, name) => page.locator(`#search-form [name="${name}"]`);

async function choose(page, name, place) {
  const input = field(page, name);
  await input.fill(place.name);
  await page.getByRole("option", { name: new RegExp(place.name) }).waitFor();
  await input.press("ArrowDown");
  await input.press("Enter");
}

async function enterConditions(page) {
  await choose(page, "from", from);
  await choose(page, "to", to);
  await field(page, "date").fill(date);
  await field(page, "time").fill("09:00");
  await page.locator('[data-buffer="10"]').click();
}

scenario("길잇 메뉴 → 장소 없음 → 검색어 수정 → 정상 경로 조회", async (page, requests) => {
  await field(page, "from").fill("일치하지 않는 장소");
  await page.getByText(/일치하는 장소가 없어요.*다른 검색어.*도로명 주소/).waitFor();
  await enterConditions(page);
  await page.locator("#search-submit").press("Enter");
  await page.waitForURL("**/pages/result.html?*");
  await page.locator(".route-card").first().waitFor();
  assert.equal(await page.locator(".route-card").count(), routes.length);
  assert.equal(requests.length, 1);
  assert.equal(new URLSearchParams(requests[0]).get("fromLat"), String(from.lat));
});

scenario("목적지 누락 시 입력 옆 안내와 포커스 이동, 다른 값 보존", async (page, requests) => {
  await choose(page, "from", from);
  await field(page, "date").fill(date);
  await field(page, "time").fill("09:00");
  await page.locator('[data-buffer="10"]').click();
  await page.locator("#search-submit").press("Enter");
  await page.locator('label.field:has([name="to"]) #to-error').waitFor();
  assert.match(await page.locator("#to-error").innerText(), /목적지.*입력/);
  assert.equal(await field(page, "to").getAttribute("aria-invalid"), "true");
  assert.equal(await page.locator(":focus").getAttribute("name"), "to");
  for (const [name, value] of Object.entries({ from: from.name, date, time: "09:00" })) {
    assert.equal(await field(page, name).inputValue(), value);
  }
  assert.equal(await page.locator('[data-buffer="10"]').getAttribute("aria-pressed"), "true");
  assert.equal(requests.length, 0);
});

scenario("경로 없음 → 키보드로 조건 수정 → 값 복원 및 재조회", async (page, requests) => {
  await enterConditions(page);
  await page.locator("#search-submit").press("Enter");
  await page.getByText("경로를 찾지 못했어요", { exact: true }).waitFor();
  assert.match(await page.locator("#route-lookup-message").innerText(), /도착 시각이나 여유시간/);
  await page.getByRole("link", { name: "조건 수정" }).press("Enter");
  await page.waitForURL("**/pages/search.html?*");
  for (const [name, value] of Object.entries({ from: from.name, to: to.name, date, time: "09:00" })) {
    assert.equal(await field(page, name).inputValue(), value);
  }
  await page.locator('[data-buffer="5"]').click();
  await page.locator("#search-submit").press("Enter");
  await page.locator(".route-card").first().waitFor();
  assert.equal(requests.length, 2);
  assert.equal(new URLSearchParams(requests[1]).get("buffer"), "5");
}, (route, count) => route.fulfill({ json: count === 1 ? [] : routes }));

for (const failure of ["HTTP 500", "네트워크 오류"]) {
  scenario(`${failure} 후 입력 보존, 키보드 재시도 및 대기 중 중복 방지`, async (page, requests) => {
    await enterConditions(page);
    await page.locator("#search-submit").press("Enter");
    const retry = page.getByRole("button", { name: "다시 조회" });
    await retry.waitFor();
    assert.match(await page.locator("#route-lookup-message").innerText(),
      failure === "HTTP 500" ? /잠시 후 다시 조회/ : /인터넷 연결을 확인/);
    assert.doesNotMatch(await page.locator("main").innerText(), new RegExp(internal));
    const conditions = new URL(page.url()).search;
    assert.equal(new URLSearchParams(conditions).get("to"), to.name);
    assert.equal(new URLSearchParams(conditions).get("buffer"), "10");

    let release;
    const pending = new Promise(done => { release = done; });
    await page.route("**/api/routes?*", async route => {
      await pending;
      await route.fallback();
    });
    try {
      await page.getByRole("link", { name: "조건 수정" }).press("Tab");
      assert.equal(await page.locator(":focus").getAttribute("id"), "route-retry");
      await page.keyboard.press("Enter");
      await page.getByText("경로를 조회하는 중이에요", { exact: true }).waitFor();
      assert.equal(await retry.getAttribute("aria-disabled"), "true");
      await page.keyboard.press("Enter");
      await retry.evaluate(button => button.click());
    } finally {
      release();
    }
    await page.locator(".route-card").first().waitFor();
    assert.equal(requests.length, 2);
    assert.equal(requests[0], requests[1]);
    assert.equal(new URL(page.url()).search, conditions);
  }, (route, count) => {
    if (count > 1) return route.fulfill({ json: routes });
    return failure === "HTTP 500"
      ? route.fulfill({ status: 500, json: { message: internal } })
      : route.abort("failed");
  });
}
