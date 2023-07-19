cd /opt/apt-local-repository/
for file in libmysqlclient-dev libmysqlclient21 mysql-client mysql-common mysql-community-client-core mysql-community-client-plugins mysql-community-client
do
    curl -Os "https://repo.mysql.com/apt/debian/pool/mysql-8.0/m/mysql-community/${file}_8.0.33-1debian10_amd64.deb"
done
echo "deb [trusted=yes] file:/opt/apt-local-repository/ ./" > /etc/apt/sources.list.d/mysql.list
cd
