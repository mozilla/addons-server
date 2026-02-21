import { spawnSync } from 'child_process';
import path from 'path';
import fs from 'fs';
import { parse } from 'dotenv';
import { describe, afterAll, it, expect } from 'vitest';

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

describe('docker-compose.yml', () => {
  afterAll(() => {
    clearEnv();
  });

  describe.for([
    ['local', 'development'],
    ['local', 'production'],
    ['latest', 'production'],
  ])('DOCKER_VERSION: %s, DOCKER_TARGET: %s', (version, target) => {
    const inputValues = {
      DOCKER_TARGET: target,
      DOCKER_VERSION: version,
      DEBUG: 'debug',
      SKIP_DATA_SEED: 'skip',
    };

    const {config, env} = getConfig(inputValues);

    it('.services.(web|worker) should have the correct configuration', () => {
      for (let service of [config.services.web, config.services.worker]) {
        expect(service.image).toStrictEqual(env.DOCKER_TAG);
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
      // nginx is mapped from http://olympia.test to port 80 in /etc/hosts on the host
      expect(config.services.nginx.ports).toStrictEqual([
        expect.objectContaining({
          mode: 'ingress',
          protocol: 'tcp',
          published: '80',
          target: 80,
        }),
      ]);
      expect(config.services.nginx.volumes).toEqual(
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
      for (let [name, service] of Object.entries(config.services)) {
        for (let volume of service.volumes ?? []) {
          if (!volume.bind && !volume.source) {
            throw new Error(
              `'.services.${name}.volumes' contains unnamed volume mount: ` +
                `'${volume.target}'. Please use a named volume mount instead.`,
            );
          }
        }
      }
    });
  });
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
    console.log(output);
    expect(output).toContain('"DOCKER_BUILD": ""');
    expect(output).toContain('"DOCKER_COMMIT": ""');
    expect(output).toContain('"DOCKER_VERSION": ""');
    expect(output).toContain('"target": "development"');
    expect(output).toContain('mozilla/addons-server:local');
  });

  describe.for([
    ['DOCKER_BUILD', 'build', '"DOCKER_BUILD": "build"'],
    ['DOCKER_COMMIT', 'commit', '"DOCKER_COMMIT": "commit"'],
    ['DOCKER_VERSION', 'latest', '"DOCKER_VERSION": "latest"'],
    ['DOCKER_VERSION', 'latest', 'mozilla/addons-server:latest'],
    ['DOCKER_DIGEST', 'sha256:digest', 'mozilla/addons-server@sha256:digest'],
    ['DOCKER_TARGET', 'production', '"target": "production"']
  ])('%s: %s', ([name, value, expected]) => {
    it(`renders custom value (${expected})`, () => {
      const output = getBakeConfig({ [name]: value });
      expect(output).toContain(expected);
    });
  });
});
