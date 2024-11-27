const { spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const { parse } = require('dotenv');

const rootPath = path.join(__dirname, '..', '..');
const envPath = path.join(rootPath, '.env');

function clearEnv() {
  fs.rmSync(envPath, { force: true });
}

function runSetup(env) {
  clearEnv();
  spawnSync('make', ['setup'], {
    env: { ...process.env, ...env },
    encoding: 'utf-8',
  });
  return parse(fs.readFileSync(envPath, { encoding: 'utf-8' }));
}

function getConfig(env = {}) {
  runSetup(env);
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
    return JSON.parse(rawConfig);
  } catch (error) {
    throw new Error(JSON.stringify({ error, rawConfig, rawError }, null, 2));
  }
}

describe('docker-compose.yml', () => {
  afterAll(() => {
    clearEnv();
  });

  it('.services.web maps environment variables to placeholders', () => {
    const values = {
      DOCKER_VERSION: 'version',
      HOST_UID: 'uid',
    };
    const {
      services: { web },
    } = getConfig(values);

    expect(web.image).toStrictEqual(
      `mozilla/addons-server:${values.DOCKER_VERSION}`,
    );
    expect(web.platform).toStrictEqual('linux/amd64');
    expect(web.environment.HOST_UID).toStrictEqual(values.HOST_UID);
  });

  it('.volumes.data_mysqld.name should map to the correct volume', () => {
    const { volumes } = getConfig();
    expect(volumes.data_mysqld.name).toStrictEqual('addons-server_data_mysqld');
  });

  it('.services.*.volumes.source should only reference named volumes', () => {
    const { services } = getConfig();

    for (let service of Object.values(services)) {
      if ('volumes' in service) {
        for (let volume of service.volumes) {
          if ('source' in volume) {
            expect(volume.source).not.toContain('.');
          }
        }
      }
    }
  });

  describe('.services.web.volumes.data_olympia_${MOUNT_OLYMPIA}', () => {
    describe.each([
      ['development', ''],
      ['development', 'development'],
      ['development', 'production'],
      ['production', ''],
      ['production', 'development'],
      ['production', 'production'],
    ])(
      'when DOCKER_TARGET is "%s" and MOUNT_OLYMPIA is "%s"',
      (target, mount) => {
        // default value of the mount is the target
        let expectedMount = target;

        // only if the target is production and the mount is not empty, we use the mount
        if (target === 'production' && mount !== '') {
          expectedMount = mount;
        }

        it(`DATA_OLYMPIA_MOUNT is "${expectedMount}"`, () => {
          const config = getConfig({
            DOCKER_TARGET: target,
            MOUNT_OLYMPIA: mount,
          });
          const {
            services: {
              web: { volumes },
            },
          } = config;

          expect(volumes).toEqual(
            expect.arrayContaining([
              expect.objectContaining({
                source: `data_olympia_${expectedMount}`,
                target: '/data/olympia',
              }),
            ]),
          );
        });
      },
    );

    it('throws an error when DATA_OLYMPIA_MOUNT is set to an invalid value', () => {
      expect(() => getConfig({ DATA_OLYMPIA_MOUNT: 'invalid' })).toThrow();
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
