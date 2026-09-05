#!/usr/bin/env python3

import os
import json
import click
import requests
import shutil
import json_merge_patch

from pathlib import Path

from contextlib import suppress

from datetime import datetime

# TODO
# 1: simplify functions to make more functional and increase maintainability
# 2: type hinting!!
# 3: completely refactor generate_profile_openapi_with_cleaned_refs to reduce complexity


def get_profile_metadata() -> dict:
    """
    Returns the profile.json file as a dict
    """
    with open("profile.json", "r") as profile_file:
        return json.load(profile_file)


def get_openapi_url_from_base_url(base_url: str) -> str:
    """
    Given a base_url for a profile, returns a URL which should resolve to that PRofile's openapi.json file if deployed
    """
    return f"{base_url}/schema/openapi.json"


def get_cache_directory_path_as_string() -> str:
    """
    This function encapsulates the string used for the cache directory's filepath, making it easier to maintain and reducing instances of hardcoded strings in the code.
    """

    return ".hsds-profile-wizard"


def get_default_hsds_schema_branch() -> str:
    """
    Queries the Github API for the HSDS Repo's information, and returns the default branch as a string

    I/O:
      * Makes a http request to query the Github API for a default branch name.
    """

    url = "https://api.github.com/repos/openreferral/specification"

    return requests.get(url).json()["default_branch"]


def fetch_schemas_from_github(branch: str) -> dict:
    """
    Retrieves the HSDS schemas from Github and returns them as dicts where the key is the filename and the value is a dict resulting from json.loads on the schema content.

    I/O:
      * makes http requests to github to retrieve HSDS schema files
    """

    url = f"https://api.github.com/repos/openreferral/specification/contents/schema?ref={branch}"

    data = json.loads(requests.get(url).text)

    schemas = {}  # "service.json => {the-service.json-schema}"

    for file in data:
        if (
            file["download_url"] is not None
        ):  # Skip directories e.g. 'compiled' and 'simple'
            schemas[file["name"]] = json.loads(requests.get(file["download_url"]).text)

    return schemas


def get_cache_metadata_filepath() -> str:
    """
    Returns the location of the cache's metadata.json file as a string
    """

    return f"{get_cache_directory_path_as_string()}/metadata.json"


def get_cache_metadata() -> dict:
    """
    Returns the cache's metadata.json file as a dict
    """

    with open(get_cache_metadata_filepath(), "r") as cache_metadata_file:
        try:
            return json.load(cache_metadata_file)
        except (FileNotFoundError, json.JSONDecodeError):
            return (
                {}
            )  # This error occurs when there's a fresh metadata.json file or not metadata.json file. This just means that there's an empty cache, or that the program thinks there's an empty cache. It's safe to return an empty dict here because that just means a fresh fetch of that branch of the HSDS schemas.


def write_cache_metadata(metadata: dict):
    """
    Writes the cache metadata to the cache's metadata.json file

    I/O:
      * Writes the metadata dict to a JSON file stored in {cache_directory}/metadata.json
    """
    with open(get_cache_metadata_filepath(), "w") as cache_metadata_file:
        cache_metadata_file.write(json.dumps(metadata))


def write_dict_of_schemas_to_directory(schemas: dict, directory: str):
    """
    Writes the dict of schemas to directory. Uses the keys of schemas as filenames, with the values (dicts) being written to the file.

    I/O:
      * Writes to the disk using the value of directory
    """

    for k, v in schemas.items():
        with open(f"{directory}/{k}", "w") as schema_file:
            schema_file.write(json.dumps(v, indent=2))


def cache_schemas(branch: str, schemas: dict):
    """
    Stores copies of the schemas in a local cache organised by branch and updates the cache metadata.json with the timestamp this branch was updated.

    I/O:
      * writes schemas to the cache directory via write_dict_of_schemas_to_directory()
    """

    cache_dir_for_branch = get_cached_schema_dir_path_from_branch(branch)

    with suppress(FileNotFoundError):
        shutil.rmtree(cache_dir_for_branch)

    os.mkdir(cache_dir_for_branch)

    write_dict_of_schemas_to_directory(schemas, cache_dir_for_branch)

    cache_metadata = get_cache_metadata()

    cache_metadata[branch] = datetime.now().isoformat()
    write_cache_metadata(cache_metadata)


def get_cached_schema_dir_path_from_branch(branch: str) -> str:
    """
    Returns the path for the directory where the cached schemas are for the given branch
    """

    return f"{get_cache_directory_path_as_string()}/{branch}"


def has_cache_directory(branch: str) -> bool:
    """
    Checks if a cache directory exist for this branch

    I/O: reads the file system to check if the path is a directory.
    """
    return os.path.isdir(get_cached_schema_dir_path_from_branch(branch))


def has_cache_metadata_entry(metadata: dict, branch: str) -> bool:
    """
    Checks if a branch of the HSDS schemas has an entry in the cache metadata
    """
    return branch in metadata


def is_cache_fresh(metadata: dict, branch: str) -> bool:
    """
    Checks if timestamp is less than a day old
    """

    try:
        cached_time = datetime.fromisoformat(metadata[branch])
        return (datetime.now() - cached_time).days <= 1
    except (ValueError, TypeError, KeyError):
        return False


def use_cached_schemas(branch: str) -> bool:
    """
    Determines whether to use the cache's metadata or not
    """
    metadata = get_cache_metadata()

    return all(
        [
            has_cache_directory(branch),
            has_cache_metadata_entry(metadata, branch),
            is_cache_fresh(metadata, branch),
        ]
    )


def fetch_schemas_from_directory(directory: str) -> dict:
    """
    Fetches Schemas from a local directory and returns a list of maps from filename to schemas. Only files ending with ".json" are fetched.

    Ignores subdirectories, only returns files.

    I/O:
      * Reads files from the directory parameter
    """

    schemas = {}

    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_file() and entry.name.endswith(".json"):
                with open(os.path.join(directory, entry.name), "r") as schema_file:
                    schemas[entry.name] = json.load(schema_file)

    return schemas


def fetch_hsds_schemas(branch: str) -> dict:
    """
    Returns a dict mapping filenames to HSDS schemas. Makes a decision about whether to use the cache or fetch fresh schemas.
    """

    if use_cached_schemas(branch):
        return fetch_schemas_from_directory(
            get_cached_schema_dir_path_from_branch(branch)
        )
    else:
        schemas = fetch_schemas_from_github(branch)
        cache_schemas(branch, schemas)
        return schemas


def generate_schema_id_from_schema_name_url_and_version(
    schema_name: str, base_url: str, version: str
) -> str:
    """
    Generates a schema $id from the schema's filename, the Profile's base_url, and the version of the Profile. https://json-schema.org/draft/2020-12/json-schema-core#name-the-id-keyword

    For most values of base_url, the assumption is that the resulting Profile schemas will be stored at {base_url}/{version}/schema/{schema_name}.json e.g. if base_url is https://example.org and the version is 0.1, then the $id value for service.json would be https://example.org/0.1/schema/service.json

    Base URLs to repos on popular source control systems are treated differently to give $id values which can resolve to the actual files. List of source control systems handled:

    https://github.com
    https://gitlab.com
    https://git.sr.ht
    https://codeberg.org
    """

    # Can't guarantee that user has omitted a trailing / or not
    # This also avoids mutations of the input
    cleaned_base_url = base_url.strip("/")

    # Define the transformation rules as a series of tuples, so that we get a purely data-driven approach to transforming the original URLs

    # Rules: (domain_prefix, replacement_prefix, path_template)
    rules = [
        (
            "https://github.com",
            "https://raw.githubusercontent.com",
            "{base}/{version}/schema/{schema_name}",
        ),
        (
            "https://gitlab.com",
            "https://gitlab.com",
            "{base}/-/raw/{version}/schema/{schema_name}",
        ),
        (
            "https://codeberg.org",
            "https://codeberg.org",
            "{base}/raw/branch/{version}/schema/{schema_name}",
        ),
        (
            "https://git.sr.ht",
            "https://git.sr.ht",
            "{base}/blob/{version}/schema/{schema_name}",
        ),
    ]

    for prefix, replacement, template in rules:
        if cleaned_base_url.startswith(prefix):
            transformed_url = cleaned_base_url.replace(prefix, replacement)
            return template.format(
                base=transformed_url, version=version, schema_name=schema_name
            )

    # Base case
    return f"{base_url}/{version}/schema/{schema_name}"


# FIXME
def generate_profile_openapi_with_cleaned_refs(
    openapi_definition: dict, profile_schemas: dict
):
    """
    Processes the openapi.json dict to replace all references to vanilla HSDS Schemas with URIs pointing to Profile schemas.

    Parameters:
      * openapi_definition: dict representing the patched openapi.json schema for the user's profile
      * profile_schemas: dict containing all the other patched profile schemas, used as a lookup to retrieve $ids to use as values for $ref

    Exceptions:
      * KeyError: When encountering a KeyError due to the lack of a profile schema with the same schema name as the $ref it's trying to replace, it will print a message to STDERR and then continue.

    Returns:
      * dict: the openapi.json file
    """
    # The API paths defined in the openapi.json file currently all point to the HSDS Schema files as a value of their $ref keys, so these need updating to the Profile's urls.
    # We have to check whether the definition of the response is a page or not, because that will affect where the $ref key lives.
    # There is also a risk here that the profile author has removed a schema from the profile, but not updated the openapi.json file to remove endpoints matching this. In these cases, raise an error message telling the user to update openapi.json
    # Personal note: writing this function nearly made me cry. It's so horrible having to manage the ridiculous tree of the openapi.json file, and then realise how haphazard and opaque the design decisions were.

    for k in openapi_definition["paths"].keys():
        # The "/" endpoint does not have any $ref values to replace and this becomes necessary after fixes to address changes in upstream HSDS
        # See https://github.com/openreferral/hsds-profile-wizard/issues/2
        if k == "/":
            continue

        # $refs can exist for each method
        for method in ["get", "post"]:
            try:
                if method in openapi_definition["paths"][k]:
                    if (
                        "$ref"
                        in openapi_definition["paths"][k][method]["responses"]["200"][
                            "content"
                        ]["application/json"]["schema"]
                    ):
                        ref_value = openapi_definition["paths"][k][method]["responses"][
                            "200"
                        ]["content"]["application/json"]["schema"]["$ref"]

                        schema_base_name_from_ref_value = Path(ref_value).name

                        openapi_definition["paths"][k][method]["responses"]["200"][
                            "content"
                        ]["application/json"]["schema"]["$ref"] = profile_schemas[
                            schema_base_name_from_ref_value
                        ][
                            "$id"
                        ]

                    # This branch executes if the path is returning paginated results
                    elif (
                        "contents"
                        in openapi_definition["paths"][k][method]["responses"]["200"][
                            "content"
                        ]["application/json"]["schema"]["allOf"][1]["properties"]
                    ):
                        ref_value = openapi_definition["paths"][k][method]["responses"][
                            "200"
                        ]["content"]["application/json"]["schema"]["allOf"][1][
                            "properties"
                        ][
                            "contents"
                        ][
                            "items"
                        ][
                            "$ref"
                        ]
                        schema_base_name_from_ref_value = Path(ref_value).name

                        openapi_definition["paths"][k][method]["responses"]["200"][
                            "content"
                        ]["application/json"]["schema"]["allOf"][1]["properties"][
                            "contents"
                        ][
                            "items"
                        ][
                            "$ref"
                        ] = profile_schemas[
                            schema_base_name_from_ref_value
                        ][
                            "$id"
                        ]

            except KeyError as e:
                # I don't like how this integrates click's printing framework tightly into the core logic of the program. I may revert this to use sys.stderr.write, or refactor it to raise the exception and push the error message to the I/O boundary of the program i.e. in the "generate" command.
                click.echo(
                    f"Error when generating openapi.json file: path {k} references schema {e} which does not appear in your Profile. Consider patching this path via profile/openapi.json",
                    err=True,
                )

    return openapi_definition


def generate_profile_schemas(
    hsds_base_schemas: dict,
    profile_source_schemas: dict,
    base_url: str,
    profile_version: str,
) -> dict:
    """
    Generates a dict of profile schemas which is the result of the following process:

    1. copying schemas which only appear in either the hsds_base_schemas or the profile_source_schemas (Symmetric Difference)
    2. patching schemas which appear in both the hsds_base_schemas and the profile_source_schemas (Intersection) according to JSON Merge Patch
    3. Overriding the $id values of each resultant schema with a new one generated from base_url and profile_version along with the name of the schema
    4. Processing `openapi.json` to replace $refs to schemas with ones pointing to the Profile's $ids
    """

    # Profiles in HSDS have the following abilities: https://docs.openreferral.org/en/latest/hsds/profiles.html
    # - leave any given HSDS Schema intact
    # - patch any given HSDS schema, including removing it, based on filename
    # - add new schemas which aren't present in the original HSDS Schemas

    # Therefore we have to handle the following:
    # - schemas which only appear in the hsds_base_schemas dict (they might not have been overridden in the Profile)
    # - schemas which only appear in the profile_source_schemas dict (they might be entirely new schemas)
    # - schemas which appear in both dicts, meaning they need patching via https://tools.ietf.org/html/rfc7386 (provided by the json_merge_patch library)

    # For the schemas we don't need to patch, we can get the Symmetric Difference of keys via combining the results of the set difference from each the hsds_base_schemas and the profile_source_schemas

    profile_schemas = {
        **{
            k: v
            for k, v in hsds_base_schemas.items()
            if k not in profile_source_schemas
        },
        **{
            k: v
            for k, v in profile_source_schemas.items()
            if k not in hsds_base_schemas
        },
    }

    # The schemas we need to patch can be represented by the intersection of keys between hsds_base_schemas and profile_source_schemas.
    # TODO: this could be made more efficient by refactoring to a map function

    schemas_to_patch = [
        k for k in hsds_base_schemas.keys() if k in profile_source_schemas
    ]

    for filename in schemas_to_patch:
        profile_schemas[filename] = json_merge_patch.merge(
            hsds_base_schemas[filename], profile_source_schemas[filename]
        )

    # Profiles can remove entire schemas by declaring a patch of `null`. In these cases, profile_schemas will contain : {"removed_schema.json": None}.
    # Therefore, it's best to remove this from the list of Profile Schemas such that they won't be processed or written to the schema/ directory later.
    # While I can see an argument for leaving them in, this will cause issues when processing the list of schemas later and I'd argue that the act of patching a schema with `null` in the profile/ directory indicates that *you do not want this schema in your profile*. Therefore it's good to remove it entirely.

    profile_schemas = {k: v for k, v in profile_schemas.items() if v is not None}

    # In JSON Schema 2020-12, schemas are identified by their `$id` which needs to be a URL which resolves to the schema.
    # Therefore we need to override any existing $id values inherited from HSDS with one derived from the Profile's base URL
    # See https://json-schema.org/draft/2020-12/json-schema-core#name-the-id-keyword
    #
    # The one exception to this is "openapi.json", which does not identify itself with an $id field.
    # See https://spec.openapis.org/oas/latest.html
    #
    # In fact, openapi.json needs processing separately because it's not a JSON Schema; it just happens to live next to the HSDS Schemas in the filetree and needs patching.
    #
    # Therefore, it's probably best to process openapi.json separately after patching, to avoid muddying up loops with conditions etc.

    open_api_definition = profile_schemas.pop("openapi.json")

    # TODO is there a better way to do this, via map functions?
    for (
        k,
        v,
    ) in profile_schemas.items():
        profile_schemas[k]["$id"] = generate_schema_id_from_schema_name_url_and_version(
            k, base_url, profile_version
        )

    profile_schemas["openapi.json"] = generate_profile_openapi_with_cleaned_refs(
        open_api_definition, profile_schemas
    )

    return profile_schemas


# ==================================
# CLI
# ==================================


@click.group()
def cli():
    """
    HSDS Profile Wizard
    """


@cli.command()
@click.option(
    "--title",
    prompt="What is the title of your Profile?",
    help="The title of your Profile",
    required=True,
)
@click.option(
    "--url",
    prompt="What is the base url of your Profile? e.g. 'https://example.org'",
    help="The base URL of your profile e.g. 'https://example-profile.org'",
    required=True,
)
@click.option(
    "--description", help="A brief human-readable description of your profile."
)
@click.option(
    "--docs-url",
    help="The url for your documentation e.g. https://docs.example-profile.org",
)
def init(title: str, url: str, description: str, docs_url: str):
    """
    Initialise a new Profile

    This command initialises a new HSDS Profile by doing the following:

    * Preparing a "profile.json" file in the current directory which contains useful metadata about the Profile\n
    * Setting up the current directory with `patches` and `schema` directories
    """

    profile_meta = {
        "title": title,
        "base_url": url,
        "openapi_url": get_openapi_url_from_base_url(url),
        "version": "0.0",
    }

    profile_meta["description"] = "" if description is None else description

    profile_meta["docs_url"] = "" if docs_url is None else docs_url

    with open("profile.json", "w") as profile_file:
        profile_file.write(json.dumps(profile_meta, indent=2))

    click.echo(
        "✓ Created profile.json based on user input — edit this file to maintain your profile's metadata between versions."
    )

    with suppress(FileExistsError):
        os.mkdir("profile")
        click.echo(
            "✓ Created 'profile/' directory — put your schema patches and new schemas here."
        )
        os.mkdir("schema")
        click.echo(
            "✓ Created 'schema/' directory — your patched schemas for your profile will be placed here."
        )

    # This is treated separately from the above, because the suppress context will block a new cache being created if the exception occurs due to 'schema' or 'profile' existing.

    with suppress(FileExistsError):
        os.mkdir(get_cache_directory_path_as_string())
        with open(
            f"{get_cache_directory_path_as_string()}/metadata.json", "w"
        ) as cache_metadata_file:
            cache_metadata_file.write("{}")
        click.echo(
            f"✓ Created '{get_cache_directory_path_as_string()}' directory — this will keep cached local copies of the HSDS schemas to save bandwidth and stop Github rate-limiting you. The program will attempt to refresh the cache if it detects that it is over 1 day old."
        )


@cli.command()
@click.option(
    "--branch",
    default=None,
    help="The branch of HSDS Schemas to use as the basis for the profile. Defaults to the latest release of HSDS",
)
@click.option(
    "--url",
    default=None,
    help="The Base URL of the Profile. Provide this to override the `base_url` property inside of profile.json",
)
@click.option(
    "--version",
    default=None,
    help="The version of the Profile you're generating. Provide this to override the `version` property inside of profile.json",
)
def generate(branch: str, url: str, version: str):
    """
    Generates Profile Schemas based on HSDS Schemas and the Patches in the `profile` directory.
    """

    if branch is None:
        branch = get_default_hsds_schema_branch()

    # Default behaviour is that the user may override properties in the profile.json file by passing arguments. If the arguments are not present, use the properties from the profile metadata

    profile_metadata = get_profile_metadata()

    if url is None:
        url = profile_metadata["base_url"]

    if version is None:
        version = profile_metadata["version"]

    profile_schemas = generate_profile_schemas(
        fetch_hsds_schemas(branch),
        fetch_schemas_from_directory("profile"),
        url,
        version,
    )

    # It's better to tidy up from previous runs, so remove the entire "schema" directory and rebuild it ready for writing
    with suppress(FileNotFoundError):
        shutil.rmtree("schema")

    os.mkdir("schema")

    write_dict_of_schemas_to_directory(profile_schemas, "schema")


@cli.command()
def gitignore():
    """Outputs some content to STDOUT which you can append to a .gitignore file"""

    git_ignore = f"{get_cache_directory_path_as_string()}"
    click.echo(git_ignore)


# ==================================
# !!! Program Entry !!!
# ==================================

if __name__ == "__main__":
    cli(obj={})
