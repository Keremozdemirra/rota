"""Finding the packages in an install command line. No network."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from support import Case, pkg_vitals as pv  # noqa: E402


def names(command, cwd="/work", env=None):
    parsed = pv.parse_command(command, cwd=cwd, env=env or {})
    return [(t["ecosystem"], t["name"], t["spec"]) for t in parsed["targets"]]


def skipped(command, env=None):
    return [(s["spec"], s["reason"]) for s in pv.parse_command(command, cwd="/work", env=env or {})["skipped"]]


class Npm(Case):
    def test_install_with_flags_and_versions(self):
        self.assertEqual(names("npm install foo bar@2 -D"), [("npm", "foo", None), ("npm", "bar", "2")])

    def test_scoped_range_and_aliases_of_install(self):
        self.assertEqual(names("npm i @scope/pkg@^2"), [("npm", "@scope/pkg", "^2")])
        for verb in ("add", "i", "isntall", "install"):
            self.assertEqual(names(f"npm {verb} x"), [("npm", "x", None)], verb)

    def test_value_options_are_not_packages(self):
        got = pv.parse_command("npm --prefix web i -w packages/app --tag beta lodash --save-prefix ~", cwd="/work",
                               env={})["targets"]
        self.assertEqual([t["name"] for t in got], ["lodash"])

    def test_private_registry_names_never_become_targets(self):
        for cmd in ("npm i lodash --registry https://npm.corp.example", "npm --registry=https://npm.corp.example i lodash",
                    "npx --registry https://npm.corp.example cowsay"):
            parsed = pv.parse_command(cmd, env={})
            self.assertEqual(parsed["targets"], [], cmd)
            self.assertIn("npm.corp.example, which pkg-vitals does not query", parsed["skipped"][0]["reason"])

    def test_public_registry_is_checked(self):
        self.assertEqual(len(pv.parse_command("npm i x --registry=https://registry.npmjs.org/", env={})["targets"]), 1)

    def test_bare_install_and_ci_install_the_lockfile(self):
        for cmd in ("npm install", "npm i -D", "npm ci", "bun install"):
            self.assertEqual(names(cmd), [], cmd)
        self.assertIn("lockfile", skipped("npm install")[0][1])

    def test_not_registry_packages_are_skipped_with_a_reason(self):
        cmd = ("npm i ./a ../b /c ~/d file:../e git+https://github.com/o/r.git github:o/r o/r "
               "https://x.org/p.tgz p.tgz foo@file:../z foo@github:o/r foo@workspace:* C:\\\\pkg")
        self.assertEqual(names(cmd), [])
        reasons = dict(skipped(cmd))
        self.assertEqual(reasons["./a"], "local path")
        self.assertEqual(reasons["git+https://github.com/o/r.git"], "git or URL")
        self.assertEqual(reasons["o/r"], "GitHub shorthand (owner/repo)")
        self.assertEqual(reasons["p.tgz"], "tarball")
        self.assertEqual(reasons["foo@workspace:*"], "local path")

    def test_name_grammar(self):
        # npm's grammar for names is lowercase; anything else stays on this machine
        self.assertEqual(names("npm i JSONStream .hidden _under 'a b' $(evil) ../../etc/passwd x" + "y" * 214), [])
        self.assertTrue(all(r in ("not a valid npm package name", "local path") for _, r in
                            skipped("npm i JSONStream .hidden _under")))

    def test_alias_installs_the_real_package(self):
        self.assertEqual(names("npm i foo@npm:bar@^1"), [("npm", "bar", "^1")])

    def test_global_install_is_a_tool(self):
        self.assertEqual(pv.parse_command("npm i -g x", env={})["targets"][0]["scope"], "tool")
        self.assertEqual(pv.parse_command("yarn global add serve", env={})["targets"][0]["via"], "yarn global add")

    def test_managers(self):
        self.assertEqual(names("pnpm add -D vitest; yarn add react@18; bun add zod"),
                         [("npm", "vitest", None), ("npm", "react", "18"), ("npm", "zod", None)])

    def test_pnpm_dir_and_filter_values(self):
        self.assertEqual(names("pnpm -C web --filter app add dayjs"), [("npm", "dayjs", None)])


class Runners(Case):
    def test_npx_takes_only_the_first_positional(self):
        self.assertEqual(names("npx -y create-next-app@latest my-app --ts --use-npm"),
                         [("npm", "create-next-app", "latest")])

    def test_package_flag_names_the_package(self):
        self.assertEqual(names("npx -p typescript -p ts-node tsc --init"),
                         [("npm", "typescript", None), ("npm", "ts-node", None)])
        self.assertEqual(names("yarn dlx -p cowsay cowsay hi; bunx -p @biomejs/biome biome check"),
                         [("npm", "cowsay", None), ("npm", "@biomejs/biome", None)])

    def test_npm_exec_and_dlx(self):
        self.assertEqual(names("npm exec -- cowsay hi; pnpm dlx degit o/r; bun x prettier ."),
                         [("npm", "cowsay", None), ("npm", "degit", None), ("npm", "prettier", None)])

    def test_npx_call_names_no_package(self):
        self.assertEqual(names("npx -c 'echo hi'"), [])

    def test_create_and_init_map_to_create_packages(self):
        self.assertEqual(names("npm create vite@latest app -- --template react"), [("npm", "create-vite", "latest")])
        self.assertEqual(names("npm init @scope/app"), [("npm", "@scope/create-app", None)])
        self.assertEqual(names("npm init @scope"), [("npm", "@scope/create", None)])
        self.assertEqual(names("yarn create react-app x"), [("npm", "create-react-app", None)])
        self.assertEqual(names("npm init -y"), [])

    def test_npx_runs_a_local_binary_without_fetching(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "node_modules" / ".bin").mkdir(parents=True)
            (Path(d) / "node_modules" / ".bin" / "tsc").write_text("")
            sub = Path(d) / "src"
            sub.mkdir()
            parsed = pv.parse_command("npx tsc --init", cwd=str(sub), env={})
            self.assertEqual(parsed["targets"], [])
            self.assertIn("node_modules/.bin", parsed["skipped"][0]["reason"])
            # a version pins a fetch even when a local binary exists
            self.assertEqual(len(pv.parse_command("npx tsc@5 --init", cwd=str(sub), env={})["targets"]), 1)

    def test_home_directory_is_not_searched(self):
        (self.home / "node_modules" / ".bin").mkdir(parents=True)
        (self.home / "node_modules" / ".bin" / "tsc").write_text("")
        project = self.home / "code" / "app"
        project.mkdir(parents=True)
        self.assertEqual(len(pv.parse_command("npx tsc", cwd=str(project), env={})["targets"]), 1)


class Python(Case):
    def test_pip_specs(self):
        got = pv.parse_command("pip install requests==2.32.0 'pkg[extra]>=1' 'b ; python_version<\"3.10\"'",
                               env={})["targets"]
        self.assertEqual([(t["name"], t["spec"], t["pin"]) for t in got],
                         [("requests", "==2.32.0", "2.32.0"), ("pkg", ">=1", None), ("b", None, None)])

    def test_prefix_match_and_odd_pins_are_not_pins(self):
        self.assertIsNone(pv.parse_command("pip install 'x==1.2.*'", env={})["targets"][0]["pin"])
        self.assertIsNone(pv.parse_command("pip install 'x==../../y'", env={})["targets"][0]["pin"])

    def test_requirement_files_editables_and_paths(self):
        cmd = "pip install -r req.txt -e ./src . ./x.whl dist/x-1.0.tar.gz 'x @ https://e.com/x.whl' git+https://h/o/r rich"
        self.assertEqual(names(cmd), [("pypi", "rich", None)])
        reasons = [r for _, r in skipped(cmd)]
        self.assertTrue(reasons[0].startswith("requirements file"))
        self.assertEqual(reasons[1], "editable install from a path or URL")

    def test_unquoted_comparison_is_a_redirect(self):
        # the shell reads `pkg>=1` as `pkg` with its output sent to a file named `=1`
        self.assertEqual(names("pip install pkg>=1"), [("pypi", "pkg", None)])

    def test_option_values_and_descriptors_are_not_packages(self):
        self.assertEqual(names("pip --python /usr/bin/python3 install --python-version 3.12 -t lib foo 2>&1"),
                         [("pypi", "foo", None)])

    def test_python_m_pip_and_versioned_pip(self):
        self.assertEqual(names("python3 -m pip install -U pip && pip3.12 install httpx && py -m pip install rich"),
                         [("pypi", "pip", None), ("pypi", "httpx", None), ("pypi", "rich", None)])

    def test_private_index_names_never_become_targets(self):
        for cmd in ("pip install -i https://user:secret@private.example/simple foo",
                    "pip install --index-url=https://private.example/simple foo",
                    "uv add --default-index https://private.example/simple foo",
                    "uv pip install --index https://private.example/simple foo",
                    "PIP_INDEX_URL=https://private.example/simple pip install foo"):
            parsed = pv.parse_command(cmd, env={})
            self.assertEqual(parsed["targets"], [], cmd)
            self.assertEqual(parsed["skipped"][0]["reason"], "installs from private.example, which pkg-vitals does not query")
        self.assertEqual(skipped("pip install --no-index -f ./wheels foo")[0][1],
                         "installs from local files (--no-index), which pkg-vitals does not query")
        self.assertEqual(names("poetry add --source corp x"), [])

    def test_index_from_the_environment(self):
        self.assertEqual(names("pip install foo", env={"PIP_INDEX_URL": "https://mirror.example/simple"}), [])
        self.assertEqual(names("pip install foo", env={"PIP_INDEX_URL": "https://pypi.org/simple"}), [("pypi", "foo", None)])

    def test_extra_index_still_asks_pypi(self):
        # pip consults PyPI as well as an extra index, so the public facts apply
        self.assertEqual(names("pip install --extra-index-url https://x.example/simple foo"), [("pypi", "foo", None)])

    def test_uv(self):
        self.assertEqual(names("uv add httpx 'fastapi[standard]>=0.110' --dev --group lint"),
                         [("pypi", "httpx", None), ("pypi", "fastapi", ">=0.110")])
        self.assertEqual(names("uv pip install -r x.txt rich"), [("pypi", "rich", None)])
        self.assertEqual(names("uv --directory app tool install ruff@0.6.0 --with black"),
                         [("pypi", "ruff", "0.6.0"), ("pypi", "black", None)])

    def test_uvx(self):
        self.assertEqual(names("uvx ruff@latest check ."), [("pypi", "ruff", None)])
        self.assertEqual(names("uvx --with rich --from 'pkg==1' cmd --with not-this"),
                         [("pypi", "pkg", "==1"), ("pypi", "rich", None)])
        self.assertEqual(names("uv tool run black ."), [("pypi", "black", None)])

    def test_poetry(self):
        got = pv.parse_command("poetry add requests@^2.31 attrs@23.1.0 -G dev ../local git+https://h/o/r", env={})
        self.assertEqual([(t["name"], t["spec"], t["pin"]) for t in got["targets"]],
                         [("requests", "^2.31", None), ("attrs", "23.1.0", "23.1.0")])

    def test_pipx(self):
        self.assertEqual(names("pipx install black 'ruff==0.6'; pipx run --spec httpie http GET x; pipx run pycowsay moo"),
                         [("pypi", "black", None), ("pypi", "ruff", "==0.6"), ("pypi", "httpie", None),
                          ("pypi", "pycowsay", None)])


class Shell(Case):
    def test_compound_lines(self):
        self.assertEqual(names("cd app&&npm i a; pip install b | tee log || yarn add c & wait"),
                         [("npm", "a", None), ("pypi", "b", None), ("npm", "c", None)])
        self.assertEqual(names("npm i a;pip install b|cat"), [("npm", "a", None), ("pypi", "b", None)])

    def test_cd_changes_where_the_project_is(self):
        got = pv.parse_command("cd web && npm i a", cwd="/work", env={})["targets"][0]
        self.assertEqual(Path(got["cwd"]), Path("/work/web"))

    def test_newlines_and_continuations(self):
        self.assertEqual(names("npm install \\\n  a \\\n  b\npip install c"),
                         [("npm", "a", None), ("npm", "b", None), ("pypi", "c", None)])

    def test_wrappers_and_assignments(self):
        self.assertEqual(names("sudo -E -u root npm i -g x; FOO=1 env -i BAR=2 pip install y; time npm i z; "
                               "timeout -s KILL 60 npm i q; nice -n 5 uvx w"),
                         [("npm", "x", None), ("pypi", "y", None), ("npm", "z", None), ("npm", "q", None),
                          ("pypi", "w", None)])

    def test_shell_c(self):
        self.assertEqual(names('bash -lc "npm i left-pad && pip install x"'), [("npm", "left-pad", None), ("pypi", "x", None)])

    def test_windows_shells(self):
        self.assertEqual(names('cmd /c "npm install left-pad"'), [("npm", "left-pad", None)])
        self.assertEqual(names("cmd.exe /C npm i a && pip install b"), [("npm", "a", None), ("pypi", "b", None)])
        self.assertEqual(names('powershell -Command "npm install x; pip install y"'), [("npm", "x", None), ("pypi", "y", None)])
        self.assertEqual(names("npm.cmd install z; python.exe -m pip install w"), [("npm", "z", None), ("pypi", "w", None)])

    def test_powershell_syntax(self):
        # what the PowerShell tool sends: `;` and, on PowerShell 7, `&&` separate commands
        self.assertEqual(names("Set-Location app; npm install a && pip install b"), [("npm", "a", None), ("pypi", "b", None)])
        self.assertEqual(Path(pv.parse_command("Set-Location app; npm i a", cwd="/w", env={})["targets"][0]["cwd"]),
                         Path("/w/app"))

    def test_heredoc_body_is_data(self):
        cmd = "cat > README.md <<'EOF'\nDon't run npm install foo\nEOF\nnpm install realpkg"
        self.assertEqual(names(cmd), [("npm", "realpkg", None)])

    def test_comments(self):
        self.assertEqual(names("npm i a # and b\npip install c"), [("npm", "a", None), ("pypi", "c", None)])

    def test_not_install_commands(self):
        for cmd in ("npm run build", "npm test", "pip list", "echo npm install foo", "git commit -m 'npm install foo'",
                    "grep 'pip install' README.md", "cat package.json", "", "   "):
            self.assertEqual(names(cmd), [], cmd)

    def test_unparseable_input_finds_nothing(self):
        for cmd in ("npm i 'unbalanced", 'pip install "x', "\x00\x01"):
            self.assertEqual(names(cmd), [], cmd)

    def test_unicode(self):
        self.assertEqual(names("echo 'héllo wörld' && npm i naïve-pkg left-pad; pip install 'café' ok"),
                         [("npm", "left-pad", None), ("pypi", "ok", None)])

    def test_duplicates_count_once(self):
        self.assertEqual(names("npm i a a && npm i a"), [("npm", "a", None)])

    def test_ignore_list(self):
        env = {"PKG_VITALS_IGNORE": "@acme/*, internal-*"}
        self.assertEqual(names("npm i @acme/ui internal-tool left-pad; pip install Internal_Lib", env=env),
                         [("npm", "left-pad", None)])

    def test_registry_from_the_environment(self):
        self.assertEqual(names("NPM_CONFIG_REGISTRY=https://npm.corp.example npm i x"), [])
        self.assertEqual(names("npm i x", env={"npm_config_registry": "https://npm.corp.example"}), [])


if __name__ == "__main__":
    unittest.main()
