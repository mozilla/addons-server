export interface PageConfig {
  path: string;
  requiresAuth: boolean;
  threshold: number;
}

export const pages: PageConfig[] = [
  {
    path: '/developers',
    requiresAuth: false,
    threshold: 0.1
  },
  {
    path: '/developers/addons',
    requiresAuth: true,
    threshold: 0.1
  }
];

export const base = {
  baseURL: process.env.BASE_URL || 'http://olympia.test',
  authEmail: process.env.AUTH_EMAIL || 'local_admin@mozilla.com',
}
