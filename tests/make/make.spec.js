import { spawnSync } from 'child_process';
import path from 'path';
import fs from 'fs';
import { parse } from 'dotenv';
import { describe, it, expect, beforeEach } from 'vitest';

const CUSTOM_DIGEST = 'sha256:124b44bfc9ccd1f3cedf4b592d4d1e8bddb78b51ec2ed5056c52d3692baebc19'

const rootPath = path.join(import.meta.dirname, '..', '..');
const envPath = path.join(rootPath, '.env.test');

function clearEnv() {
  fs.rmSync(envPath, { force: true });
}

beforeEach(() => {
  clearEnv();
});

afterAll(() => {
  clearEnv();
});

function runSetup(env, isBuild = false) {
  clearEnv();
  // Run setup in dry-mode to get the printed env back.
  const result = spawnSync('make', [
    'setup', `SETUP_ARGS=--env-file ${envPath} ${isBuild ? '--build' : ''}`
  ], {
    env: { ...process.env, ...env },
    encoding: 'utf-8',
  });
  if (result.stderr) {
    throw new Error(result.stderr);
  }
  const file = fs.readFileSync(envPath, { encoding: 'utf-8' });
  return parse(file);
}

function makeJsonOutput(command, env = {}, isBuild = false) {
  const rawEnv = runSetup(env, isBuild);
  const { stdout: rawConfig, stderr: rawError } = spawnSync(
    'make',
    [command, `ENV_FILE=${envPath}`],
    {
      encoding: 'utf-8',
      env: { ...process.env, ...rawEnv },
    },
  );
  try {
    if (rawError) throw new Error(rawError);
    const firstBraceIndex = rawConfig.indexOf('{');
    const lastBraceIndex = rawConfig.lastIndexOf('}');
    if (firstBraceIndex === -1 || lastBraceIndex === -1 || lastBraceIndex < firstBraceIndex) {
      throw new Error('Could not find valid JSON object braces in make output.');
    }
    const jsonString = rawConfig.substring(firstBraceIndex, lastBraceIndex + 1);
    const result = {
      config: JSON.parse(jsonString),
      env: rawEnv,
    };
    return result;
  } catch (error) {
    throw new Error(
      JSON.stringify({ error: error.message, rawConfig, rawError, rawEnv }, null, 2),
    );
  }
}

describe('docker-compose.yml', () => {
  describe.for([
    ['local', 'development'],
    ['local', 'production'],
    ['latest', 'production'],
  ])('DOCKER_TAG: %s, DOCKER_TARGET: %s', ([tag, target]) => {
    const {config, env} = makeJsonOutput('docker_compose_config', {
      DOCKER_TARGET: target,
      DOCKER_TAG: tag,
    });

    describe.for(['web', 'worker'])('.service.%s', (name) => {
      const service = config.services[name];
      it('should have the correct configuration', () => {
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
      });

      it('should have correct environment configuration', () => {
        expect(service.environment).toEqual(expect.objectContaining(env));
      })
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
  it('renders empty values for undefined variables', () => {
    const {config: {target: {web}}} = makeJsonOutput('docker_bake_config');
    expect(web).toStrictEqual({
      context: '.',
      dockerfile: 'Dockerfile',
      args: {
        DOCKER_BUILD: '',
        DOCKER_COMMIT: '',
        DOCKER_SOURCE: 'https://github.com/mozilla/addons-server',
        DOCKER_TARGET: 'development',
        DOCKER_VERSION: 'local'
      },
      tags: [ 'mozilla/addons-server:local' ],
      target: 'development',
      platforms: [ 'linux/amd64' ],
      output: [ 'type=docker' ],
      pull: true
    });
  });

  describe.for([
    ['custom/image:latest', 'custom/image:latest', true],
    ['latest', 'mozilla/addons-server:latest', true],
    ['latest@sha256:124b44bfc9ccd1f3cedf4b592d4d1e8bddb78b51ec2ed5056c52d3692baebc19', `mozilla/addons-server:latest@${CUSTOM_DIGEST}`, false],
  ])('%s: %s', ([value, expected, isBuild]) => {
    it(`renders custom DOCKER_TAG ${isBuild ? '' : 'not'} building`, () => {
      const {config: {target: {web}}} = makeJsonOutput('docker_bake_config', {
        DOCKER_TAG: value,
        // Pass required args for build if isBuild is true.
        ...(isBuild ? {
          DOCKER_BUILD: 'build',
          DOCKER_COMMIT: 'commit',
        } : {}),
      }, isBuild);
      expect(web.tags).toStrictEqual([expected]);
      if (isBuild) {
        expect(web.args.DOCKER_BUILD).toStrictEqual('build');
        expect(web.args.DOCKER_COMMIT).toStrictEqual('commit');
      }
    });
  });
});
