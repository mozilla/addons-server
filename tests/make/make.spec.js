import { spawnSync } from 'child_process';
import { parse } from 'dotenv';
import fs from 'fs';
import path from 'path';

const rootPath = path.join(import.meta.dirname, '..', '..');
const envPath = path.join(rootPath, '.env');

function clearEnv() {
  fs.rmSync(envPath, { force: true });
}

function runSetup(env) {
  clearEnv();
  const result = spawnSync('make', ['setup'], {
    env: { ...process.env, ...env },
    encoding: 'utf-8',
  });
  if (result.stderr) {
    throw new Error(result.stderr);
  }
  return parse(fs.readFileSync(envPath, { encoding: 'utf-8' }));
}

function getConfig(env = {}) {
  const rawEnv = runSetup(env);
  const { stdout: rawConfig, stderr: rawError } = spawnSync(
    'docker',
    ['compose', 'config', '--format', 'json'],
    {
      encoding: 'utf-8',
      env: { ...process.env, ...env },
    },
  );
  try {
    if (rawError) throw new Error(rawError);
    return {
      config: JSON.parse(rawConfig),
      env: rawEnv,
    };
  } catch (error) {
    throw new Error(
      JSON.stringify({ error, rawConfig, rawError, rawEnv }, null, 2),
    );
  }
}

function permutations(configObj) {
  return Object.entries(configObj).reduce((acc, [key, values]) => {
    if (!acc.length) return values.map((value) => ({ [key]: value }));
    return acc.flatMap((obj) =>
      values.map((value) => ({ ...obj, [key]: value })),
    );
  }, []);
}

describe('docker-compose.yml', () => {
  afterAll(() => {
    clearEnv();
  });

  describe.each(
    permutations({
      DOCKER_TARGET: ['development', 'production'],
      DOCKER_VERSION: ['local', 'latest'],
    }),
  )('\n%s\n', (config) => {
    const { DOCKER_TARGET, DOCKER_VERSION } = config;

    const inputValues = {
      DOCKER_TARGET,
      DOCKER_VERSION,
      DEBUG: 'debug',
      SKIP_DATA_SEED: 'skip',
    };

    it('.services.(web|worker) should have the correct configuration', () => {
      const {
        config: {
          services: { web, worker },
        },
        env: { DOCKER_TAG },
      } = getConfig(inputValues);

      for (let service of [web, worker]) {
        expect(service.image).toStrictEqual(DOCKER_TAG);
        expect(service.pull_policy).toStrictEqual('never');
        expect(service.user).toStrictEqual('root');
        expect(service.platform).toStrictEqual('linux/amd64');
        expect(service.entrypoint).toStrictEqual([
          '/data/olympia/docker/entrypoint.sh',
        ]);
        expect(service.extra_hosts).toStrictEqual(['olympia.test=127.0.0.1']);
        expect(service.restart).toStrictEqual('on-failure:5');
        // Each service should have a healthcheck
        expect(service.healthcheck).toHaveProperty('test');
        expect(service.healthcheck.interval).toStrictEqual('30s');
        expect(service.healthcheck.retries).toStrictEqual(3);
        expect(service.healthcheck.start_interval).toStrictEqual('1s');
        // each service should have a command
        expect(service.command).not.toBeUndefined();
        // each service should have the same dependencies
        expect(service.depends_on).toEqual(
          expect.objectContaining({
            autograph: expect.any(Object),
            elasticsearch: expect.any(Object),
            memcached: expect.any(Object),
            mysqld: expect.any(Object),
            rabbitmq: expect.any(Object),
            redis: expect.any(Object),
          }),
        );
        expect(service.volumes).toEqual(
          expect.arrayContaining([
            expect.objectContaining({
              source: expect.any(String),
              target: '/data/olympia',
            }),
          ]),
        );
        const { DOCKER_VERSION, DOCKER_TARGET, ...environmentOutput } =
          inputValues;
        expect(service.environment).toEqual(
          expect.objectContaining({
            ...environmentOutput,
          }),
        );
        // We excpect not to pass the input values to the container
        expect(service.environment).not.toHaveProperty('OLYMPIA_UID');
      }
    });

    it('.services.nginx should have the correct configuration', () => {
      const {
        config: {
          services: { nginx },
        },
      } = getConfig(inputValues);
      // nginx is mapped from http://olympia.test to port 80 in /etc/hosts on the host
      expect(nginx.ports).toStrictEqual([
        expect.objectContaining({
          mode: 'ingress',
          protocol: 'tcp',
          published: '80',
          target: 80,
        }),
      ]);
      expect(nginx.volumes).toEqual(
        expect.arrayContaining([
          // mapping for nginx conf.d adding addon-server routing
          expect.objectContaining({
            source: 'data_nginx',
            target: '/etc/nginx/templates',
          }),
          // mapping for /data/olympia/ directory to /srv
          expect.objectContaining({
            source: expect.any(String),
            target: '/srv',
          }),
        ]),
      );
    });

    it('.services.*.volumes does not contain anonymous or unnamed volumes', () => {
      const {
        config: { services },
      } = getConfig(inputValues);
      for (let [name, config] of Object.entries(services)) {
        for (let volume of config.volumes ?? []) {
          if (!volume.bind && !volume.source) {
            throw new Error(
              `'.services.${name}.volumes' contains unnamed volume mount: ` +
                `'${volume.target}'. Please use a named volume mount instead.`,
            );
          }
        }
      }
    });

    const EXCLUDED_KEYS = ['DOCKER_COMMIT', 'DOCKER_VERSION', 'DOCKER_BUILD'];
    // This test ensures that we do NOT include environment variables that are used
    // at build time in the container. Cointainer environment variables are dynamic
    // and should not be able to deviate from the state at build time.
    it('.services.(web|worker).environment excludes build info variables', () => {
      const {
        config: {
          services: { web, worker },
        },
      } = getConfig({
        ...inputValues,
        ...Object.fromEntries(EXCLUDED_KEYS.map((key) => [key, 'filtered'])),
      });
      for (let service of [web, worker]) {
        for (let key of EXCLUDED_KEYS) {
          expect(service.environment).not.toHaveProperty(key);
        }
      }
    });
  });

  // these keys require special handling to prevent runtime errors in make setup
  const failKeys = [
    // Invalid docker tag leads to docker not parsing the image
    'DOCKER_TAG',
  ];
  const ignoreKeys = [
    // Ignored because these values are explicitly mapped to the host_* values
    'OLYMPIA_UID',
    // Ignored because the HOST_UID is always set to the host user's UID
    'HOST_UID',
  ];
  const defaultEnv = runSetup();
  const customValue = 'custom';

  describe.each(Array.from(new Set([...Object.keys(defaultEnv), ...failKeys])))(
    `custom value for environment variable %s=${customValue}`,
    (key) => {
      if (failKeys.includes(key)) {
        it('config should fail if set to an arbitrary custom value', () => {
          expect(() =>
            getConfig({ DOCKER_TARGET: 'production', [key]: customValue }),
          ).toThrow();
        });
      } else if (ignoreKeys.includes(key)) {
        it('variable should be ignored', () => {
          const {
            config: {
              services: { web, worker },
            },
          } = getConfig({ ...defaultEnv, [key]: customValue });
          for (let service of [web, worker]) {
            expect(service.environment).not.toEqual(
              expect.objectContaining({
                [key]: customValue,
              }),
            );
          }
        });
      } else {
        it('variable should be overriden based on the input', () => {
          const {
            config: {
              services: { web, worker },
            },
          } = getConfig({ ...defaultEnv, [key]: customValue });
          for (let service of [web, worker]) {
            expect(service.environment).toEqual(
              expect.objectContaining({
                [key]: customValue,
              }),
            );
          }
        });
      }
    },
  );
});

describe('docker-bake.hcl', () => {
  afterAll(() => {
    clearEnv();
  });

  function getBakeConfig(env = {}) {
    runSetup(env);
    const { stdout: output } = spawnSync(
      'make',
      ['docker_build_web', 'ARGS=--print'],
      {
        encoding: 'utf-8',
        env: { ...process.env, ...env },
      },
    );

    return output;
  }
  it('renders empty values for undefined variables', () => {
    const output = getBakeConfig();
    expect(output).toContain('"DOCKER_BUILD": ""');
    expect(output).toContain('"DOCKER_COMMIT": ""');
    expect(output).toContain('"DOCKER_VERSION": ""');
    expect(output).toContain('"target": "development"');
    expect(output).toContain('mozilla/addons-server:local');
  });

  it('renders custom DOCKER_BUILD', () => {
    const build = 'build';
    const output = getBakeConfig({ DOCKER_BUILD: build });
    expect(output).toContain(`"DOCKER_BUILD": "${build}"`);
  });

  it('renders custom DOCKER_COMMIT', () => {
    const commit = 'commit';
    const output = getBakeConfig({ DOCKER_COMMIT: commit });
    expect(output).toContain(`"DOCKER_COMMIT": "${commit}"`);
  });

  it('renders custom DOCKER_VERSION', () => {
    const version = 'version';
    const output = getBakeConfig({ DOCKER_VERSION: version });
    expect(output).toContain(`"DOCKER_VERSION": "${version}"`);
    expect(output).toContain(`mozilla/addons-server:${version}`);
  });

  it('renders custom DOCKER_DIGEST', () => {
    const digest = 'sha256:digest';
    const output = getBakeConfig({ DOCKER_DIGEST: digest });
    expect(output).toContain(`mozilla/addons-server@${digest}`);
  });

  it('renders custom target', () => {
    const target = 'target';
    const output = getBakeConfig({ DOCKER_TARGET: target });
    expect(output).toContain(`"target": "${target}"`);
  });
});
