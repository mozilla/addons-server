// Every request has to be mocked (vi.mock the api module, or stub `fetch`).
// A real one goes to happy-dom's default origin, so the test would hinge on
// whatever is listening there. The query layer swallows the rejection, so
// tests/setup.ts fails the test from afterEach instead.
const unmockedRequests: string[] = [];

export function installNetworkGuard() {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    unmockedRequests.push(url);
    throw new TypeError(`Unmocked fetch: ${url}`);
  }) as typeof fetch;
}

export function takeUnmockedRequests(): string[] {
  return [...new Set(unmockedRequests.splice(0))];
}
