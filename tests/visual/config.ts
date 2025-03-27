export interface PageConfig {
  path: string;
  requiresAuth: boolean;
  threshold: number;
}

export const pages: PageConfig[] = [
  {
    path: '/developers',
    requiresAuth: false,
    threshold: 0
  },
  {
    path: '/developers/addons',
    requiresAuth: true,
    threshold: 0
  },
  {
    path: '/developers/themes',
    requiresAuth: true,
    threshold: 0
  },
  {
    path: '/developers/addon/{guid}/edit',
    requiresAuth: true,
    threshold: 0
  },
  {
    path: '/developers/addon/{guid}/ownership',
    requiresAuth: true,
    threshold: 0
  },
  {
    path: '/developers/addon/{guid}/versions',
    requiresAuth: true,
    threshold: 0
  },
  {
    path: '/developers/addon/{guid}/versions/{version}',
    requiresAuth: true,
    threshold: 0
  },
  {
    path: '/reviewers/review/{version}',
    requiresAuth: true,
    threshold: 0
  }
];

export const base = {
  baseURL: process.env.BASE_URL || 'http://olympia.test',
  authEmail: process.env.AUTH_EMAIL || 'local_admin@mozilla.com',
}
