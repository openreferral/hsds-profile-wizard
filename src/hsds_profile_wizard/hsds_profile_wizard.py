#!/usr/bin/env python3

import os
import sys
import json
import jsonref
import click
import requests
import shutil
import json_merge_patch

from pathlib import Path

from compiletojsonschema.compiletojsonschema import CompileToJsonSchema

from contextlib import suppress

from datetime import datetime


def get_default_list_of_schemas_to_compile():
    """
    Returns a list containing: ["service.json", "organization.json", "location.json", "service_at_location.json"]

    This represents the "core objects" of HSDS, so should be a sensible default for a list of schemas to compile. See https://docs.openreferral.org/en/latest/hsds/schema_reference.html#core-objects

    Returns:
     * list: list of strings representing the schema names of the HSDS Core objects.
    """

    return [
        "service.json",
        "organization.json",
        "location.json",
        "service_at_location.json",
    ]


def get_list_of_schemas_to_compile(profile_metadata):
    """
    Retrieves a list of strings which match keys in a dict of schemas, indicating whether that schema should be compiled or not.

    It does this via the following process:

    * Checks for the presence of a "compile" property in the profile_metadata and that it is not null
    * If present, it returns the list of schemas declared in profile_metadata["compile"], even if empty
    * Else, it returns a list of: "service.json", "organization.json", "location.json", and "service_at_location.json".

    Parameters:
      * profile_metadata (dict): the metadata of the profile, usually read in from profile.json elsewhere

    Returns:
      * list: list of strings representing schema filenames to compile e.g. "service.json"
    """

    # In HSDS, the canonical schemas are compiled underneath the "schema/compiled" directory, and the openapi.json file uses the compiled schemas as the definitions of the return schemas for API endpoints. Profiles should also follow this pattern (although they have the ability to explicitly override it)
    # Profiles also have the ability to declare new schemas and remove existing schemas, so we need to determine *which* of the patched Profile schemas we need to compile. We've got no guarantee that HSDS schemas still exist in the Profile (note: this is handled elsewhere), but it's possible that the Profile has added entirely new schemas that they'd like compiled for returning in the API.
    # To account for these cases, we allow the Profile author to manually declare which of their Profile schemas they want to be compiled, via a property in their `profile.json` file.
    # However, it may be that the Profile is only making small adjustments to the HSDS Schemas and else wants some sensible defaults. They might have deliberately omitted the "compile" property in the `profile.json` file.
    # For these cases, we return a list of the "core objects" in HSDS, as it's relatively safe to assume these should be compiled.
    # See: https://docs.openreferral.org/en/latest/hsds/schema_reference.html#core-objects

    if "compile" in profile_metadata:
        if profile_metadata["compile"] is not None:
            return profile_metadata["compile"]
    else:

        return get_default_list_of_schemas_to_compile()


def get_profile_metadata():
    """
    Returns the profile.json file as a dict

    Returns:
      * dict: the profile.json object
    """
    with open("profile.json", "r") as profile_file:
        return json.load(profile_file)


def get_openapi_url_from_base_url(base_url):
    """
    Given a base_url for a profile, returns a URL which should resolve to that PRofile's openapi.json file if deployed

    Parameters:
      * base_url: string (uri), the base_url for the profile. Usually taken from profile.json.

    Returns:
      * string: a string representing the location of the Open API URL for the profile.
    """
    return f"{base_url}/schema/openapi.json"


def get_cache_directory_path_as_string():
    """
    This function encapsulates the string used for the cache directory's filepath, making it easier to maintain and reducing instances of hardcoded strings in the code.

    Returns:
      * string: the direcory of the cache
    """

    return ".hsds-profile-wizard"


def get_default_hsds_schema_branch():
    """
    Queries the Github API for the HSDS Repo's information, and returns the default branch as a string

    I/O:
      * Makes a http request to query the Github API for a default branch name.

    Returns:
      * string: the default branch of the HSDS repository e.g. "3.2"
    """

    url = "https://api.github.com/repos/openreferral/specification"

    return requests.get(url).json()["default_branch"]


def fetch_schemas_from_github(branch):
    """
    Retrieves the HSDS schemas from Github and returns them as dicts

    I/O:
      * makes http requests to github to retrieve HSDS schema files

    Parameters:
        branch (str): Which branch of the HSDS Schemas to use.

    Returns:
        dict of HSDS Schemas where the key is the filename and the value is a dict resulting from json.loads on the schema content.
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


def get_cache_metadata_filepath():
    """
    Returns the location of the cache's metadata.json file as a string

    Return:
      * str: the filepath to the cache's metadata.json file
    """

    return f"{get_cache_directory_path_as_string()}/metadata.json"


def get_cache_metadata():
    """
    Returns the cache's metadata.json file as a dict

    Returns:
      * dict - resulting from json.loads on the metadata file
    """

    with open(get_cache_metadata_filepath(), "r") as cache_metadata_file:
        try:
            return json.load(cache_metadata_file)
        except (FileNotFoundError, json.JSONDecodeError):
            return (
                {}
            )  # This error occurs when there's a fresh metadata.json file or not metadata.json file. This just means that there's an empty cache, or that the program thinks there's an empty cache. It's safe to return an empty dict here because that just means a fresh fetch of that branch of the HSDS schemas.


def write_cache_metadata(metadata):
    """
    Writes the cache metadata to the cache's metadata.json file

    Parameters:
      * metadata (dict): the dict representing the current cache's metadata

    I/O:
      * Writes the metadata dict to a JSON file stored in {cache_directory}/metadata.json
    """
    with open(get_cache_metadata_filepath(), "w") as cache_metadata_file:
        cache_metadata_file.write(json.dumps(metadata))


def write_dict_of_schemas_to_directory(schemas, directory):
    """
    Writes the dict of schemas to directory. Uses the keys of schemas as filenames, with the values being written to the file.

    Parameters:
      * schemas (dict): a dict of schemas e.g. {'example.json': {…}}
      * directory (str): the directory to write each schema

    I/O:
      * Writes to the disk using the value of directory
    """

    for k, v in schemas.items():
        with open(f"{directory}/{k}", "w") as schema_file:
            schema_file.write(json.dumps(v, indent=2))


def cache_schemas(branch, schemas):
    """
        Stores copies of the schemas in a local cache organised by branch and updates the cache metadata.json with the timestamp this branch was updated.
    ault_list_of_schemas_to_compile()
                "service.json",
                "organization.json",
                "location.json",
                "service_at_location.json",
            ]

        Parameters:
            branch (str): the branch of the repo
            schemas (dict): a dict of filenames=>schemas to write to the cache

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


def get_cached_schema_dir_path_from_branch(branch):
    """
    Returns the path for the directory where the cached schemas are for the given branch

    Parameters:
      * branch (str): the branch name of the set of schemas to retrieve e.g. "3.2"

    Return:
        str: the path of the directory where the cached schemas would be for the given branch
    """

    return f"{get_cache_directory_path_as_string()}/{branch}"


def use_cached_schemas(branch):
    """
    Looks at the cache's metadata.json entry for the branch and decided whether to use the cached schemas or not based on the current time. If no entry is present, it defaults to returning False

    Parameters:
      * branch (str): the branch for which to check for cached schemas

    Return:
      bool: whether to use the cached schemas for that branch or not.
    """

    # If we don't have any cached files for this branch, we can't use the cache
    if not os.path.isdir(get_cached_schema_dir_path_from_branch(branch)):
        return False

    try:
        cache_metadata = get_cache_metadata()

        # If the branch isn't in the cache metadata, we can return early. This check might not be necessary because we've already checked for the branch's cache directory earlier, but it's worthwhile doing here to ensure that the metadata.json file is behaving properly.
        if branch not in cache_metadata:
            return False

        try:
            current_datetime = datetime.now()
            cached_schemas_datetime = datetime.fromisoformat(cache_metadata[branch])

            # Only use the cache if it's less than a day old. There's probably better heuristics than this out there, but this seems like an inoffensive place to start.
            return (
                True
                if (current_datetime - cached_schemas_datetime).days <= 1
                else False
            )
        except (ValueError, TypeError):
            # Invalid date format in the metadata, so treat as an invalid cache and refresh it
            return False

    except (FileNotFoundError, PermissionError, OSError):
        # These exceptions likely mean that there's no cache metadata file, or it's not usable for some reason. It's OK to say false not to use the cache here.
        return False


def fetch_schemas_from_directory(directory):
    """
    Fetches Schemas from a local directory and returns a list of maps from filename to schemas. Only files ending with ".json" are fetched.

    Ignores subdirectories, only returns files.

    Parameters:
      * directory (str): the directory to scan for JSON files

    I/O:
      * Reads files from the directory parameter

    Returns:
        * schemas (dict): dicts mapping filenames to schemas
    """

    schemas = {}

    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_file() and entry.name.endswith(".json"):
                with open(os.path.join(directory, entry.name), "r") as schema_file:
                    schemas[entry.name] = json.load(schema_file)

    return schemas


def fetch_hsds_schemas(branch):
    """
    Returns a dict mapping filenames to HSDS schemas. Makes a decision about whether to use the cache or fetch fresh schemas.

    Parameters:
      * branch (str): which branch of the HSDS schemas to fetch e.g. "3.2"

    Return:
        * schemas (dict): list of dicts mapping filenames to schemas loaded into memory as dicts
    """

    if use_cached_schemas(branch):
        return fetch_schemas_from_directory(
            get_cached_schema_dir_path_from_branch(branch)
        )
    else:
        schemas = fetch_schemas_from_github(branch)
        cache_schemas(branch, schemas)
        return schemas


def generate_schema_id_from_schema_name_url_and_version(schema_name, base_url, version):
    """
    Generates a schema $id from the schema's filename, the Profile's base_url, and the version of the Profile. https://json-schema.org/draft/2020-12/json-schema-core#name-the-id-keyword

    For most values of base_url, the assumption is that the resulting Profile schemas will be stored at {base_url}/{version}/schema/{schema_name}.json e.g. if base_url is https://example.org and the version is 0.1, then the $id value for service.json would be https://example.org/0.1/schema/service.json

    There are some notable exceptions to account for popular source control systems, which are treated differently to give $id values which can resolve to the actual files. List of source control systems handled:

    https://github.com/user/repo -> https://raw.githubusercontent.com/{version}/schema/{schema_name}
    https://gitlab.com/user/repo -> https://gitlab.com/user/repo/-/raw/{version}/schema/{schema_name}
    https://git.sr.ht/~user/repo_name -> https://git.sr.ht/~user/repo/blob/{version}/schema/{schema_name}
    https://codeberg.org/user/repo -> https://codeberg.org/user/repo/raw/branch/{version}/schema/{schema_name}

    Parameters:
      * schema_name (str): the name of the schema file e.g. "service.json"
      * base_url (str): the base URL for the profile e.g. https://example.org
      * version (str): the version string for the Profile e.g. 0.1, 2020-12, etc.

    Returns:
      * str: the $id string to a Profile schema based on the provided schema name, base url, and version
    """

    # Can't guarantee that user has omitted a trailing / or not
    base_url = base_url.strip("/")

    if base_url.startswith("https://github.com"):
        return f"{base_url.replace('https://github.com', 'https://raw.githubusercontent.com')}/{version}/schema/{schema_name}"

    if base_url.startswith("https://gitlab.com"):
        return f"{base_url}/-/raw/{version}/{schema_name}"

    if base_url.startswith("https://git.sr.ht"):
        return f"{base_url}/blob/{version}/schema/{schema_name}"

    if base_url.startswith("https://codeberg.org"):
        return f"{base_url}/raw/branch/{version}/{schema_name}"

    return f"{base_url}/{version}/schema/{schema_name}"


def generate_profile_openapi_with_cleaned_refs(openapi_definition, profile_schemas):
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
    # In some cases, these need updating to the "compiled" schema identifier, and in others just the base schema. There doesn't appear to be a specific reason for this named in any of the HSDS docs, so we just have to inspect the $ref and if it contains "compiled" then it should use the compiled schema.
    # Further, we have to check whether the definition of the response is a page or not, because that will affect where the $ref key lives.
    # There is also a risk here that the profile author has removed a schema from the profile, but not updated the openapi.json file to remove endpoints matching this. In these cases, raise an error message telling the user to update openapi.json
    # Personal note: writing this function nearly made me cry. It's so horrible having to manage the ridiculous tree of the openapi.json file, and then realise how haphazard and opaque the design decisions were.

    for k in openapi_definition["paths"].keys():
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

                        if "compiled" in ref_value:
                            openapi_definition["paths"][k][method]["responses"]["200"][
                                "content"
                            ]["application/json"]["schema"][
                                "$ref"
                            ] = generate_compiled_schema_id_from_schema_id(
                                profile_schemas[schema_base_name_from_ref_value]["$id"]
                            )
                        else:
                            openapi_definition["paths"][k][method]["responses"]["200"][
                                "content"
                            ]["application/json"]["schema"]["$ref"] = profile_schemas[
                                schema_base_name_from_ref_value
                            ][
                                "$id"
                            ]
                    elif (
                        "contents"
                        in openapi_definition["paths"][k][method]["responses"]["200"][
                            "content"
                        ]["application/json"]["schema"]["properties"]
                    ):
                        ref_value = openapi_definition["paths"][k][method]["responses"][
                            "200"
                        ]["content"]["application/json"]["schema"]["properties"][
                            "contents"
                        ][
                            "items"
                        ][
                            "$ref"
                        ]
                        schema_base_name_from_ref_value = Path(ref_value).name
                        if "compiled" in ref_value:
                            openapi_definition["paths"][k][method]["responses"]["200"][
                                "content"
                            ]["application/json"]["schema"]["properties"]["contents"][
                                "items"
                            ][
                                "$ref"
                            ] = generate_compiled_schema_id_from_schema_id(
                                profile_schemas[schema_base_name_from_ref_value]["$id"]
                            )
                        else:
                            openapi_definition["paths"][k][method]["responses"]["200"][
                                "content"
                            ]["application/json"]["schema"]["properties"]["contents"][
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
    hsds_base_schemas, profile_source_schemas, base_url, profile_version
):
    """
    Generates a dict of profile schemas which is the result of the following process:

    1. copying schemas which only appear in either the hsds_base_schemas or the profile_source_schemas (Symmetric Difference)
    2. patching schemas which appear in both the hsds_base_schemas and the profile_source_schemas (Intersection) according to JSON Merge Patch
    3. Overriding the $id values of each resultant schema with a new one generated from base_url and profile_version along with the name of the schema
    4. Processing `openapi.json` to replace $refs to schemas with ones pointing to the Profile's $ids

    Parameters:
        * hsds_base_schemas (dict): mapping of schema filename to schema dict e.g. {'example.json': {}}
        * profile_source_schemas (dict): mapping of schema filename to schema dict e.g. {'example.json': {}}
        * base_url (string): the url used as the base url of the profile, used to set the $id properties of schemas
        * profile_version: the version of the profile, used to set the $id properties of schemas

    Returns:
        * dict: mapping of schema filenames to schema dict e.g {'example.json': {…}}, representing all the schemas present in the profile, fully patched, with new $id values.
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


def generate_compiled_schema_id_from_schema_id(schema_id):
    """
    Generates a compiled schema's $id value given the value of an existing $id

    Currently, this amounts to replacing "schema" with "schema/compiled" between the head of the uri and the tail

    Parameters:
      * schema_id (str) the schema $id from which to generate the compiled schema id e.g. https://example.org/0.0.1/schema/example.json

    Returns:
      * str: the $id value of the compiled schema
    """

    return schema_id.replace("schema", "schema/compiled")


def generate_compiled_schema(schema_name):
    """
    Generates a compiled (de-referenced) schema based on an input file name, and outputs it as a dict.

    Parameters:
      * schema_name (str): the name of the schema to read from the schema directory e.g. service.json

    I/O:
      * Reads a schema file from `schema/{schema_name}`, this is due to the CompileToJsonSchema library requiring a filepath. This will also result in it reading other schema files and performing HTTP requests based on any $ref values present in the source schema. See https://github.com/OpenDataServices/compile-to-json-schema.

    Exceptions:
      * FileNotFoundError: occurs if the compiler is given the path to a non-existant schemafile to compile. Most likely due to a schema being removed entirely from a Profile but not removing it from the list of schemas to compile in profile.json
      * jsonref.JsonRefError: occurs if the compiler fails to resolve a $ref key inside a schema file it's compiling. Most likely due to a schema file being removed entirely from a Profile, but the Profile author neglecting to patch out $refs to it in other schemas.

    Returns:
      * dict: a dict representing the compiled schema
    """

    try:

        compiler = CompileToJsonSchema(input_filename=f"schema/{schema_name}")
        compiled_schema = compiler.get()

        # The compiled schema currently has the $id of the original schema, so we need to modify it to play nicely with openapi.json and the directory structure of how HSDS schemas/profiles work

        compiled_schema["$id"] = generate_compiled_schema_id_from_schema_id(
            compiled_schema["$id"]
        )

        return compiled_schema
    except FileNotFoundError:
        # This is most likely to occur when the user has excluded one of the default HSDS Schemas from their Profile, but is still trying to use the default list of schemas to compile.
        raise FileNotFoundError(
            f"Error: could not generate compiled schema from {schema_name}. This usually occurs when you are trying to compile a schema which doesn't exist in your Profile. You should either re-add the schema to your Profile, or manually set which schemas to compile via profile.json"
        )
    except jsonref.JsonRefError as e:
        # This is most likely to occur due to a schema being excluded from the Profile, but then being involved in a compilation step via a $ref in the schema being compiled now.
        raise jsonref.JsonRefError(
            f"Error while generating a compiled schema from /schema/{schema_name}. Could not resolve a $ref to {e.reference['$ref']} when compiling this schema. It's likely that you have removed {e.reference['$ref']} from your profile, so you should create /profile/{schema_name} to patch this schema and remove any references to {e.reference['$ref']} ",
            e.reference,
        )


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
def init(title, url, description, docs_url):
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
        "compile": get_default_list_of_schemas_to_compile(),
    }

    profile_meta["description"] = "" if description is None else description

    profile_meta["docs_url"] = "" if docs_url is None else docs_url

    with open("profile.json", "w") as profile_file:
        profile_file.write(json.dumps(profile_meta, indent=2))

    click.echo(
        "✓ Created profile.json based on user input — edit this file to maintain your profile's metadata between versions and control how schemas compile"
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
def generate(branch, url, version):
    """
    Generates and compiles Profile Schemas based on HSDS Schemas and the Patches in the `profile` directory.
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

    # The compiletojsonschema library requires a file as input, so we need to write out the contents of profile_schemas now before compiling.
    # This needs to be done anyway, but it's a little messy to have I/O in the middle of a chain of processing if we're not in a UNIX pipe imho.
    # Unfortunately, this is easier than re-implementing the logic to compile a schema.

    # It's better to tidy up from previous runs, so remove the entire "schema" directory and rebuild it ready for writing
    with suppress(FileNotFoundError):
        shutil.rmtree("schema")

    os.mkdir("schema")

    write_dict_of_schemas_to_directory(profile_schemas, "schema")

    names_of_schemas_to_compile = get_list_of_schemas_to_compile(profile_metadata)

    try:

        compiled_schemas = {}
        for name in names_of_schemas_to_compile:
            compiled_schemas[name] = generate_compiled_schema(name)

        os.mkdir("schema/compiled")

        write_dict_of_schemas_to_directory(compiled_schemas, "schema/compiled")
    except FileNotFoundError as e:
        click.echo(e, err=True)
        sys.exit(1)
    except jsonref.JsonRefError as e:
        click.echo(e, err=True)
        sys.exit(1)


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
