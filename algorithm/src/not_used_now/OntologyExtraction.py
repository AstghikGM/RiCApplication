import json
import os
from rdflib import Graph, Namespace, RDF, OWL, RDFS

class OntologyExtraction:
    """
    Pre-process heavy RDF ontologies into lightweight JSON schemas.
    """
    RICO = Namespace("https://www.ica.org/standards/RiC/ontology#")

    def __init__(self, rdf_path="/algorithm/src/RiC_Ontology/RiC-O_1-1.rdf"):
        self.rdf_path = rdf_path
        self.g = Graph()

    def create_schema(self, output_json="/algorithm/src/RiC_Ontology/RiC-O_1-1_schema.json"):
        if not os.path.exists(self.rdf_path):
            print(f"Error: {self.rdf_path} not found.")
            return

        print(f"Parsing {self.rdf_path}...")
        self.g.parse(self.rdf_path, format="xml")

        classes = set()
        properties = set()

        # 1. Classes (entities) extraction
        for s in self.g.subjects(RDF.type, OWL.Class):
            name = self._get_local_name(s)
            if name and not name.startswith("RiCCM"):
                classes.add(name)

        # 2. Properties (attributes and relationship) extraction
        prop_types = [OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property]
        for t in prop_types:
            for s in self.g.subjects(RDF.type, t):
                name = self._get_local_name(s)
                if name and not name.startswith("RiCCM"):
                    properties.add(name)

        schema_data = {
            "ontology": "RiC-O",
            "version": "1.1",
            "total_classes": len(classes),
            "total_properties": len(properties),
            "classes": sorted(list(classes)),
            "properties": sorted(list(properties))
        }

        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(schema_data, f, indent=4, ensure_ascii=False)
        

    def _get_local_name(self, uri):
        uri_str = str(uri)
        if uri_str.startswith(str(self.RICO)):
            return uri_str.split("#")[-1]
        return None
