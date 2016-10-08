#!groovy
timestamps {
    node {
        checkout scm
        docker.withRegistry('https://5gex.tmit.bme.hu') {
            def image = docker.build("tnova-connector:1.0.0.${env.BUILD_NUMBER}")
            image.push()
            image.push('latest')
        }
    }
}
