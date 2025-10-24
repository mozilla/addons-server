# Troubleshooting and Debugging

Effective troubleshooting and debugging practices are essential for maintaining and improving the **addons-server** project. This section covers common issues, their solutions, and tools for effective debugging.

## DEV_MODE vs DEBUG

In our project, `DEV_MODE` and `DEBUG` serve distinct but complementary purposes.
`DEV_MODE` is directly tied to the `DOCKER_TARGET` build argument and is used to enable or disable behaviors
based on whether we are running a production image or not.

For instance, production images always disables certain features like using fake fxa authentication. Additionally,
certain dependencies are only installed in [dev.txt](../../../requirements/dev.txt) and so must be disabled in production.

Conversely, `DEBUG` controls the activation of debugging tools and utilities, such as the debug_toolbar,
which are useful for troubleshooting. Unlike DEV_MODE, DEBUG is independent
and can be toggled in both development and production environments as needed.

This separation ensures that essential behaviors are managed according to the deployment target (DEV_MODE),
while allowing flexibility to enable or disable debugging features (DEBUG) in production or development images.

## Common Issues and Solutions

1. **Containers Not Starting**:
   - **Issue**: Docker containers fail to start.
   - **Solution**: Ensure that Docker is running and that no other services are using the required ports. Use the following command to start the containers:

     ```sh
     make up
     ```

2. **Database Connection Errors**:
   - **Issue**: The application cannot connect to the MySQL database.
   - **Solution**: Verify that the MySQL container is running and that the connection details in the `.env` file are correct. Restart the MySQL container if necessary:

     ```sh
     make down
     make up
     ```

3. **Missing Dependencies**:
   - **Issue**: Missing Python or Node.js dependencies.
   - **Solution**: Ensure that all dependencies are installed by running the following command:

     ```sh
     make up
     ```

4. **Locale Compilation Issues**:
   - **Issue**: Locales are not compiling correctly.
   - **Solution**: Run the locale compilation command and check for any errors:

     ```sh
     make compile_locales
     ```

5. **Permission Issues**:
   - **Issue**: Permission errors when accessing files or directories.
   - **Solution**: Ensure that the `olympia` user has the correct permissions. Use `chown` or `chmod` to adjust permissions if necessary.

## Debugging

You can access the management server from a shell to run things like `ipdb`.

### Using `ipdb`

To debug with `ipdb`, add a line in your code at the relevant point:

```python
breakpoint()
```

You can connect to the debugger when testing or running shell commands. E.g.

```sh
pytest src/olympia/addons/tests/test_models.py::TestAddon -x --pdbcls=IPython.core.debugger:Pdb --pdb
```

This wil launch a debugger during a test at the point there's an exception or failure allowing you to debug the issue.

### Logging

Logs for the Celery and Django processes can be found on your machine in the `logs` directory.

### Using the Django Debug Toolbar

The `Django Debug Toolbar` is a powerful tool for viewing various aspects of your pages, such as the view used, parameters, SQL queries, templates rendered, and their context.

To use it, see the official getting started docs: [Django Debug Toolbar Installation](https://django-debug-toolbar.readthedocs.io/en/1.4/installation.html#quick-setup)

**Note**:

- The Django Debug Toolbar can slow down the website. Mitigate this by deselecting the checkbox next to the `SQL` panel.
- Use the Django Debug Toolbar only when needed, as it affects CSP report only for your local dev environment.
- You might need to disable CSP by setting `CONTENT_SECURITY_POLICY_REPORT_ONLY = CONTENT_SECURITY_POLICY_REPORT;CONTENT_SECURITY_POLICY_REPORT = {}` in your local settings because the Django Debug Toolbar uses "data:" for its logo and "unsafe eval" for some panels like templates or SQL.

## Additional Debugging Tools

1. **Interactive Shell**:
   - Use the interactive shell to debug issues directly within the Docker container.
   - Access the shell with:

     ```sh
     make shell
     ```

2. **Django Shell**:
   - The Django shell is useful for inspecting and manipulating the application state at runtime.
   - Access the Django shell with:

     ```sh
     make djshell
     ```

3. **Logs**:
   - Checking logs is a crucial part of debugging. Logs for each service can be accessed using Docker Compose.
   - View logs with:

     ```sh
     docker-compose logs
     ```

4. **Database Inspection**:
   - Inspect the database directly to verify data and diagnose issues.
   - Use a MySQL client or access the MySQL container:

     ```sh
     make dbshell
     ```

5. **Browser Developer Tools**:
   - Use browser developer tools for debugging frontend issues. Inspect network requests, view console logs, and profile performance to identify issues.

6. **VSCode Remote Containers**:
   - If you use Visual Studio Code, the Remote - Containers extension can help you develop inside the Docker container with full access to debugging tools.

## Additional Tips

1. **Ensure Containers Are Running**:
   - Always check if the Docker containers are running. If you encounter issues, restarting the containers often resolves temporary problems.

2. **Environment Variables**:
   - Double-check environment variables in the `.env` file. Incorrect values can cause configuration issues.

3. **Network Issues**:
   - Ensure that your Docker network settings are correct and that there are no conflicts with other services.

4. **Use Specific Makefiles**:
   - If you encounter issues with Makefile commands, you can force the use of a specific Makefile to ensure the correct environment is used:

     ```sh
     make -f Makefile-docker <command>
     ```

By following these troubleshooting and debugging practices, developers can effectively diagnose and resolve issues in the **addons-server** project. For more detailed instructions, refer to the project's Makefile and Docker Compose configuration in the repository.
