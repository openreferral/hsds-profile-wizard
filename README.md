HSDS Profile Wizard
======================

A Python-based CLI tool which makes it straightforward to create and manage your HSDS Profile.


## Features

* Handles `$id` values: your Profile schemas and their compiled variants will all have `$id` values set based on your Profile's base URL. This will also handle a potential upgrade to HSDS, so you don't need to manually override `$id` in every schema
* No hidden compilation steps: you can patch HSDS schemas with the full assurance that the tool is not manually inserting any arrays or relationships
* Full control over Profile schema compilation: declare which of your profile schemas you want to compile, with sensible defaults if you don't need this much control
* Cacheing: avoid Github rate-limiting by storing a local copy of HSDS Schemas in the `.hsds-profile-wizard` directory of your project.

## Installation

Installation is via `pip` or `pipx`:

```bash
# Install inside a virtual environment with pip
python3 -m venv .ve
source .ve/bin/activate
pip install git+https://github.com/openreferral/hsds-profile-wizard@main

# Install system-wide with pipx
pipx install git+https://github.com/openreferral/hsds-profile-wizard@main
```

## Usage

### Quick Start

```bash
# Answer prompts to generate the profile.json file describing your profile. You can also pass them in as CLI flags e.g. --title --url --description --docs-url
hsds-profile-wizard init

# Generate and compile your patched Profile schemas based on the default branch of HSDS
hsds-profile-wizard generate 

# Generate and compile your patched Profile Schemas based on a specific branch of HSDS
hsds-profile-wizard generate --branch "3.0"

# You can also pass in flags to override the default settings in your profile.json
hsds-profile-wizard generate --branch "3.0" --version "0.2" --url "https://not-my-default-profile-url.org"
```

### Basic Usage

The basic workflow of the HSDS Profile Wizard is:

1. Establish the basic settings for your Profile via `profile.json`, which contains metadata for your Profile. You can generate one by running the `init` command.
2. Write your schema patches in the `profile/` directory
3. Run the `generate` command to generate your profile schemas under `schema/`. You can choose to base your profile off of a specific version of HSDS by passing the `--branch` argument. It will otherwise use the default branch of the [HSDS Specification](https://github.com/openreferral/specification) repo.

### Declaring which schemas are compiled

In HSDS, the "compiled" schemas are the canonical views of the schemas, however Profiles have the ability to remove schemas via patching them with `null`, and also have the ability to add new schemas which they may want to have compiled.

This means the HSDS Profile Wizard allows users to declare which schemas they wish to compile for their profile. This is done by adding the name of the schema to the `compile` array inside of `profile.json`.

If no `compile` key is present inside of `profile.json`, HSDS Profile Wizard attempts to compile the following schemas:

* `service.json`
* `organization.json`
* `service_at_location.json`
* `location.json`

This is because they are stated as the *core objects* in the HSDS Schema Reference:

* https://docs.openreferral.org/en/latest/hsds/schema_reference.html

### Errors generating openapi.json

It's likely that the first few times you run this tool, you will see messages like this:

```
Error when generating openapi.json file: path /services references schema 'service_list.json' which does not appear in your Profile. Consider patching this path via profile/openapi.json
```
This occurs because HSDS Profile Wizard has attempted to update a `$ref` to a schema in one of the API paths in your Profile's openapi.json file (to make it point to where your Profile's schemas will live), but it cannot find the schema inside the list of your patched profile schemas.

The underlying reason for these errors being present is that the upstream HSDS' openapi.json file relies on specific compilations being performed to result in `service_list.json`and `organization_list.json`. HSDS Profile Wizard does not perform these compilations because there is no guarantee that the schemas required for these compilations are present in your Profile.

You have two options:

1. Patch the `openapi.json` file and edit which schemas are returned by these endpoints (recommended)
2. Add your own schemas named `organization_list.json` and `service_list.json` in the `profile/` directory and tell the HSDS Profile Wizard to compile them.
