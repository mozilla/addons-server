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

  it('.services.mysqld should have the correct configuration', () => {
    const {
      services: { mysqld },
    } = getConfig();
    // MYSQL_DATABASE should be set to olympia so the container will create
    // the olympia database on startup
    expect(mysqld.environment.MYSQL_DATABASE).toStrictEqual('olympia');
    // mysqld should mount data_mysqld volume to /var/lib/mysql
    // this volume is the external persistent storage for the database
    expect(mysqld.volumes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: 'data_mysqld',
          target: '/var/lib/mysql',
        }),
      ]),
    );
  });

  it.each(['production', 'development'])(
    '.services.nginx should have the correct configuration for OLYMPIA_MOUNT_INPUT=%s',
    (OLYMPIA_MOUNT_INPUT) => {
      const {
        services: { nginx },
      } = getConfig({
        OLYMPIA_MOUNT_INPUT,
        // set docker target to production to ensure we are allowed
        // to override the olympia mount
        DOCKER_TARGET: 'production',
      });
      // nginx is mapped from http://olympia.test to port 80 in /etc/hosts on the host
      expect(nginx.ports).toStrictEqual([
        expect.objectContaining({
          mode: 'ingress',
          protocol: 'tcp',
          published: '80',
          target: 80,
        }),
      ]);
      expect(nginx.depends_on).toEqual(
        expect.objectContaining({
          // nginx must start after web to avoid race conditions mounting data_site_static
          web: expect.any(Object),
        }),
      );
      expect(nginx.volumes).toEqual(
        expect.arrayContaining([
          // mapping for nginx conf.d adding addon-server routing
          expect.objectContaining({
            source: 'data_nginx',
            target: '/etc/nginx/conf.d',
          }),
          // mapping for local host directory to /data/olympia
          expect.objectContaining({
            source: `data_olympia_${OLYMPIA_MOUNT_INPUT}`,
            target: '/data/olympia',
          }),
        ]),
      );
    },
  );

  it('.services.(web|worker) should inherit olympia', () => {
    const {
      services: { web, worker },
    } = getConfig({
      DOCKER_TAG: 'mozilla/addons-server:tag',
    });

    for (let service of [web, worker]) {
      expect(service.image).toStrictEqual('mozilla/addons-server:tag');
      expect(service.pull_policy).toStrictEqual('never');
      expect(service.user).toStrictEqual('root');
      expect(service.platform).toStrictEqual('linux/amd64');
      expect(service.entrypoint).toStrictEqual([
        '/data/olympia/docker/entrypoint.sh',
      ]);
      expect(service.extra_hosts).toStrictEqual(['olympia.test=127.0.0.1']);
      expect(service.restart).toStrictEqual('on-failure:5');
      // Each service should have a healthcheck
      expect(service.healthcheck.test).not.toBeUndefined();
      expect(service.healthcheck.interval).toStrictEqual('1m30s');
      expect(service.healthcheck.retries).toStrictEqual(3);
      expect(service.healthcheck.start_interval).toStrictEqual('1s');
      expect(service.healthcheck.start_period).toStrictEqual('2m0s');
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
    }
    // TODO: web and worker should have the correct volumes
    // data_site_static, data_static_build, data_olympia and data_storage
  });

  // these keys require special handling to prevent runtime errors in make setup
  const ignoreKeys = [
    'DOCKER_TAG',
    'OLYMPIA_MOUNT_INPUT',
    'OLYMPIA_MOUNT',
    'DOCKER_TARGET',
  ];
  const defaultEnv = runSetup();
  const customValue = 'custom';

  describe.each(
    Array.from(new Set([...Object.keys(defaultEnv), ...ignoreKeys])),
  )(`environment variable %s=${customValue}`, (key) => {
    const ignored = ignoreKeys.includes(key);

    if (ignored) {
      it('should fail if set to an arbitrary custom value', () => {
        expect(() =>
          getConfig({ DOCKER_TARGET: 'production', [key]: customValue }),
        ).toThrow();
      });
    } else {
      it('should be overriden based on the input', () => {
        const {
          services: { web, worker },
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
  });

  it('.services.web maps environment variables to placeholders', () => {
    const values = {
      DOCKER_VERSION: 'version',
      OLYMPIA_UID: '9500',
    };
    const {
      services: { web },
    } = getConfig(values);

    expect(web.image).toStrictEqual(
      `mozilla/addons-server:${values.DOCKER_VERSION}`,
    );
    expect(web.platform).toStrictEqual('linux/amd64');
    expect(web.environment.OLYMPIA_UID).toStrictEqual(values.OLYMPIA_UID);
  });

  it('.volumes.data_mysqld.name should map to the correct volume', () => {
    const { volumes } = getConfig();
    expect(volumes.data_mysqld.name).toStrictEqual('addons-server_data_mysqld');
  });

  describe.each(['production', 'development'])(
    '.services.*.volumes for OLYMPIA_MOUNT_INPUT=%s',
    (OLYMPIA_MOUNT_INPUT) => {
      it('duplicate volumes should be defined on services.olympia.volumes', () => {
        const { services } = getConfig({ OLYMPIA_MOUNT_INPUT });
        // volumes defined on the olympia service, any dupes in other services should be here also
        const olympiaVolumes = new Set(
          Object.values(services.olympia.volumes).map((v) => v.source),
        );

        // all volumes defined on any service other than olympia
        const allVolumes = Object.entries(services)
          // only include non olympia services with volumes
          .filter(
            ([name, service]) =>
              name !== 'olympia' && Array.isArray(service.volumes),
          )
          .map(([name, service]) =>
            service.volumes.filter((v) => !v.bind).map((v) => [name, v.source]),
          )
          .flat();

        const uniqueVolumes = new Set();
        const duplicateVolumes = new Set();

        // duplicate volumes should be defined on the olympia service
        // to ensure that the volume is mounted by docker before any
        // other service tries to use it.
        for (let [name, source] of allVolumes) {
          if (uniqueVolumes.has(source)) {
            duplicateVolumes.add(source);
            if (!olympiaVolumes.has(source)) {
              throw new Error(
                `service ${name} has duplicate volume ${source} not defined on olympia`,
              );
            }
          } else {
            uniqueVolumes.add(source);
          }
        }

        // any service that depends on a duplicate volume must also depend on olympia
        for (let [name, source] of allVolumes) {
          if (
            duplicateVolumes.has(source) &&
            !services[name].depends_on?.olympia
          ) {
            throw new Error(
              `service ${name} depends on duplicate volume ${source} but does not depend on olympia`,
            );
          }
        }
      });
    },
  );

  it('.services.*.volumes.source should only reference unique named volumes', () => {
    const { services, volumes } = getConfig();
    const uniqueVolumes = new Set();

    for (let [name, service] of Object.entries(services)) {
      if ('volumes' in service) {
        for (let volume of service.volumes) {
          // name of the volume or bind path
          const volumeName = volume.source;
          // the defintion of the volume on the top level compose file
          const volumeDefinition = volumes[volumeName];
          // whether the volume is external as defined in the top level compose file
          const isExternal = volumeDefinition?.external;
          // whether the volume is a bind mount
          const isBind = volume?.bind;
          // is olympia
          const isOlympia = name === 'olympia';

          // for non bind and non external volumes, we should not mount the same
          // volume to more than one service, otherwise we could have race conditions
          if (
            !isOlympia &&
            !isBind &&
            !isExternal &&
            uniqueVolumes.has(volumeName)
          ) {
            // If we have a duplicate volume, we should ensure it is defined
            // on the olympia service and that the current service depends on it
            const isVolumeOnOlympia = services.olympia.volumes.some(
              (v) => v.source === volumeName,
            );
            const isServiceDependentOnOlympia = service.depends_on?.olympia;

            if (!isVolumeOnOlympia && !isServiceDependentOnOlympia) {
              throw new Error(
                `Duplicate volume ${volumeName} not defined on olympia and is not a dependency`,
              );
            }
          }

          uniqueVolumes.add(volumeName);

          if ('source' in volume) {
            expect(volume.source.substring(0, 1)).not.toStrictEqual('.');
          }
        }
      }
    }
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
